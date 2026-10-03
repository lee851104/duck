using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace LineOcrMonitor
{
    internal sealed class Target
    {
        public long Handle;
        public int Pid;
        public string StartedUtc;
        public string Title;
        public override string ToString() { return Title + " [PID " + Pid + "]"; }
    }

    internal static class WindowCapture
    {
        [StructLayout(LayoutKind.Sequential)] internal struct Rect { public int L,T,R,B; }
        [StructLayout(LayoutKind.Sequential)] internal struct PointNative { public int X,Y; }
        internal delegate bool EnumCallback(IntPtr h, IntPtr p);
        [DllImport("user32.dll")] internal static extern bool EnumWindows(EnumCallback f, IntPtr p);
        [DllImport("user32.dll")] internal static extern bool IsWindowVisible(IntPtr h);
        [DllImport("user32.dll")] internal static extern bool IsIconic(IntPtr h);
        [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll", CharSet=CharSet.Unicode)] internal static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
        [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
        [DllImport("user32.dll")] internal static extern bool GetClientRect(IntPtr h, out Rect r);
        [DllImport("user32.dll")] internal static extern bool GetWindowRect(IntPtr h, out Rect r);
        [DllImport("user32.dll")] internal static extern bool ClientToScreen(IntPtr h, ref PointNative p);
        [DllImport("user32.dll")] internal static extern bool SetProcessDPIAware();
        [DllImport("dwmapi.dll")] internal static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int size);
        internal static string Title(IntPtr h) { var s=new StringBuilder(4096); GetWindowText(h,s,s.Capacity); return s.ToString(); }
        internal static Target Describe(IntPtr h)
        {
            uint pid; GetWindowThreadProcessId(h,out pid);
            using(var p=Process.GetProcessById((int)pid))
            {
                if(!String.Equals(p.ProcessName,"LINE",StringComparison.OrdinalIgnoreCase)) throw new Exception("目標不是 LINE。");
                return new Target { Handle=h.ToInt64(), Pid=(int)pid, StartedUtc=p.StartTime.ToUniversalTime().ToString("o"), Title=Title(h) };
            }
        }
        internal static bool Same(Target a, Target b) { return a!=null && b!=null && a.Handle==b.Handle && a.Pid==b.Pid && a.StartedUtc==b.StartedUtc && a.Title==b.Title; }
        internal static List<Target> List()
        {
            var list=new List<Target>();
            EnumWindows(delegate(IntPtr h,IntPtr p) { if(IsWindowVisible(h)) { try { var t=Describe(h); if(t.Title.Length>0) list.Add(t); } catch { } } return true; },IntPtr.Zero);
            return list;
        }
        internal static Rectangle Bounds(Target t)
        {
            var h=new IntPtr(t.Handle);
            if(!Same(t,Describe(h))) throw new Exception("視窗身分或社群標題已改變；請停止後重新選擇。");
            if(IsIconic(h)) throw new Exception("暫停擷取：LINE 已最小化。");
            if(GetForegroundWindow()!=h) throw new Exception("暫停擷取：請將指定 LINE 社群放到最前方。");
            Rect r; var p=new PointNative();
            if(!GetClientRect(h,out r) || !ClientToScreen(h,ref p)) throw new Exception("無法取得 LINE 畫面範圍。");
            var b=new Rectangle(p.X,p.Y,r.R-r.L,r.B-r.T);
            if(b.Width<=0 || b.Height<=0 || !Screen.AllScreens.Any(s=>s.Bounds.Contains(b))) throw new Exception("請將 LINE 視窗完整放在同一個螢幕內。");
            return b;
        }
        internal static bool Within(Rectangle roi, Size size) { return roi.Width>=40 && roi.Height>=40 && new Rectangle(Point.Empty,size).Contains(roi); }
        internal static void Uncovered(Target t, Rectangle region)
        {
            bool reached=false, blocked=false;
            EnumWindows(delegate(IntPtr h,IntPtr p) {
                if(h.ToInt64()==t.Handle) { reached=true; return false; }
                if(IsWindowVisible(h) && !IsIconic(h)) {
                    int cloaked; Rect r;
                    if(DwmGetWindowAttribute(h,14,out cloaked,4)==0 && cloaked!=0) return true;
                    if(GetWindowRect(h,out r) && region.IntersectsWith(Rectangle.FromLTRB(r.L,r.T,r.R,r.B))) { blocked=true; return false; }
                }
                return true;
            },IntPtr.Zero);
            if(blocked || !reached) throw new Exception("暫停擷取：LINE 上方有其他視窗或浮動面板，請移開。");
        }
        internal static Bitmap Read(Target t, Rectangle? roi, Size? expected)
        {
            var b=Bounds(t);
            if(expected.HasValue && b.Size!=expected.Value) throw new Exception("LINE 視窗尺寸已改變，請停止後重新框選。");
            var local=roi ?? new Rectangle(Point.Empty,b.Size);
            if(!Within(local,b.Size)) throw new Exception("請先框選至少 40 × 40 的留言區域。");
            var region=new Rectangle(b.X+local.X,b.Y+local.Y,local.Width,local.Height);
            Uncovered(t,region);
            var bitmap=new Bitmap(region.Width,region.Height,PixelFormat.Format32bppArgb);
            try {
                using(var g=Graphics.FromImage(bitmap)) g.CopyFromScreen(region.Location,Point.Empty,region.Size,CopyPixelOperation.SourceCopy);
                if(Bounds(t)!=b) throw new Exception("擷取途中 LINE 視窗移動，這張畫面已捨棄。");
                Uncovered(t,region);
                return bitmap;
            } catch { bitmap.Dispose(); throw; }
        }
    }

    internal sealed class OcrResult
    {
        public string Status { get;set; }
        public string Text { get;set; }
        public string Error { get;set; }
    }
    internal sealed class FrameGate
    {
        private string last;
        internal bool Changed(string hash) { return last!=hash; }
        internal void Commit(string hash) { last=hash; }
    }
    internal static class Ocr
    {
        internal static readonly UTF8Encoding Utf8=new UTF8Encoding(false);
        internal static readonly JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=16000000 };
        internal static string Root=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,".."));
        internal static string Quote(string value) { if(value.Contains("\"")) throw new ArgumentException("Invalid quote in path"); return "\""+value+"\""; }
        internal static string DisplayText(string raw) { return Regex.Replace(raw ?? "", @"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", ""); }
        internal static string Hash(Bitmap image)
        {
            using(var ms=new MemoryStream()) using(var sha=SHA256.Create()) { image.Save(ms,ImageFormat.Png); return BitConverter.ToString(sha.ComputeHash(ms.ToArray())).Replace("-",""); }
        }
        internal static OcrResult Run(string original, string prefix)
        {
            string input=prefix+".ocr-input.png", output=prefix+".ocr.json";
            int width,height; double scale;
            using(var src=new Bitmap(original)) {
                width=src.Width; height=src.Height;
                scale=Math.Min(2.0,2500.0/Math.Max(width,height));
                using(var dst=new Bitmap(Math.Max(1,(int)(width*scale)),Math.Max(1,(int)(height*scale)),PixelFormat.Format32bppArgb))
                using(var g=Graphics.FromImage(dst)) {
                    g.Clear(Color.White); g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.DrawImage(src,0,0,dst.Width,dst.Height); dst.Save(input,ImageFormat.Png);
                }
            }
            var start=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe"));
            start.Arguments="-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "+Quote(Path.Combine(Root,"OcrWorker.ps1"))+" -ImagePath "+Quote(input)+" -OutputPath "+Quote(output);
            start.UseShellExecute=false; start.CreateNoWindow=true; start.WindowStyle=ProcessWindowStyle.Hidden;
            using(var worker=Process.Start(start)) {
                if(!worker.WaitForExit(30000)) { try { worker.Kill(); } catch { } throw new Exception("OCR 超過 30 秒，已停止本工具的 OCR 子程序。"); }
                if(!File.Exists(output)) throw new Exception("OCR 未產生報告；請確認 Windows PowerShell 可執行。");
            }
            var result=Json.Deserialize<OcrResult>(File.ReadAllText(output,Utf8));
            if(result.Status!="recognized") throw new Exception("OCR 失敗："+result.Error);
            var info=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(output,Utf8));
            info["OriginalWidth"]=width; info["OriginalHeight"]=height; info["Scale"]=scale;
            info["CoordinateSpace"]="Words are in ocr-input.png pixels; divide by Scale for source pixels.";
            info["ReadableText"]=DisplayText(result.Text);
            File.WriteAllText(output,Json.Serialize(info),Utf8);
            File.WriteAllText(prefix+".txt", "OCR 原文；未驗證作者、訊息邊界、數量或完整性。\r\n"+DisplayText(result.Text),Utf8);
            return result;
        }
    }

    internal sealed class RegionView : Control
    {
        internal Bitmap Image;
        internal Rectangle Selection { get; set; }
        private Point anchor;
        private bool dragging;
        internal Action SelectionChanged;
        internal RegionView() { DoubleBuffered=true; BackColor=Color.FromArgb(235,239,243); Cursor=Cursors.Cross; }
        internal RectangleF ImageRect {
            get { if(Image==null) return RectangleF.Empty; float s=Math.Min((float)Width/Image.Width,(float)Height/Image.Height); return new RectangleF((Width-Image.Width*s)/2,(Height-Image.Height*s)/2,Image.Width*s,Image.Height*s); }
        }
        internal Point ToImage(Point p) { var r=ImageRect; return new Point(Math.Max(0,Math.Min(Image.Width,(int)((p.X-r.X)*Image.Width/r.Width))),Math.Max(0,Math.Min(Image.Height,(int)((p.Y-r.Y)*Image.Height/r.Height)))); }
        protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); if(Image==null || e.Button!=MouseButtons.Left || !ImageRect.Contains(e.Location)) return; anchor=ToImage(e.Location); dragging=true; Capture=true; Selection=Rectangle.Empty; }
        protected override void OnMouseMove(MouseEventArgs e) { base.OnMouseMove(e); if(!dragging) return; var p=ToImage(e.Location); Selection=Rectangle.FromLTRB(Math.Min(p.X,anchor.X),Math.Min(p.Y,anchor.Y),Math.Max(p.X,anchor.X),Math.Max(p.Y,anchor.Y)); Invalidate(); }
        protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); if(!dragging) return; dragging=false; Capture=false; if(SelectionChanged!=null) SelectionChanged(); }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e); if(Image==null) { e.Graphics.DrawString("先取得預覽，再拖曳框選留言區\n請排除頂端公告和底部輸入框",Font,Brushes.DimGray,20,20); return; }
            var r=ImageRect; e.Graphics.DrawImage(Image,r);
            if(!Selection.IsEmpty) using(var pen=new Pen(Color.DeepSkyBlue,3)) e.Graphics.DrawRectangle(pen,r.X+Selection.X*r.Width/Image.Width,r.Y+Selection.Y*r.Height/Image.Height,Selection.Width*r.Width/Image.Width,Selection.Height*r.Height/Image.Height);
        }
        internal void SetImage(Bitmap image) { if(Image!=null) Image.Dispose(); Image=image; Selection=Rectangle.Empty; Invalidate(); }
        protected override void Dispose(bool disposing) { if(disposing && Image!=null) Image.Dispose(); base.Dispose(disposing); }
    }

    internal sealed class MonitorForm : Form
    {
        private ComboBox windows=new ComboBox { DropDownStyle=ComboBoxStyle.DropDownList, Width=530 };
        private Button refresh,calibrate,start,stop,openFile;
        private Label status=new Label { Dock=DockStyle.Fill, AutoSize=false, ForeColor=Color.FromArgb(0,80,130), TextAlign=ContentAlignment.MiddleLeft };
        private TextBox output=new TextBox { Multiline=true, ReadOnly=true, ScrollBars=ScrollBars.Both, WordWrap=false, Dock=DockStyle.Fill, Font=new Font("Microsoft JhengHei UI",11) };
        private RegionView view=new RegionView { Dock=DockStyle.Fill };
        private System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer { Interval=3000 };
        private Target calibratedTarget;
        private Size calibratedSize;
        private Rectangle roi;
        private bool busy,monitoring;
        private string session, lastEvent, journalError;
        private FrameGate gate=new FrameGate();
        private int frames;
        internal MonitorForm(bool preview)
        {
            Text="LINE 一般留言 OCR 測試 v0.1 — 本機辨識"; Width=1120; Height=840; MinimumSize=new Size(1000,700); Font=new Font("Microsoft JhengHei UI",10); StartPosition=FormStartPosition.CenterScreen;
            var layout=new TableLayoutPanel { Dock=DockStyle.Fill, ColumnCount=1, RowCount=5, Padding=new Padding(14) };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute,60)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,45)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,50)); layout.RowStyles.Add(new RowStyle(SizeType.Percent,100)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,65));
            layout.Controls.Add(new Label { Dock=DockStyle.Fill, Text="一般留言｜自動截圖與文字保存\n先開好社群並停在最新訊息；程式只擷取你框選的畫面，不自動捲動。", AutoSize=false },0,0);
            var targets=new FlowLayoutPanel { Dock=DockStyle.Fill, WrapContents=false };
            targets.Controls.Add(windows); refresh=Button("重新整理視窗",delegate { RefreshWindows(); }); targets.Controls.Add(refresh);
            openFile=Button("測試現有圖片",async delegate { await LoadFile(); }); targets.Controls.Add(openFile); layout.Controls.Add(targets,0,1);
            var actions=new FlowLayoutPanel { Dock=DockStyle.Fill, WrapContents=false };
            calibrate=Button("1. 取得預覽（5秒後）",async delegate { await Calibrate(); });
            start=Button("2. 開始每 3 秒監看",delegate { try { Start(); } catch(Exception ex) { monitoring=false; timer.Stop(); UpdateButtons(); Say("無法開始："+ex.Message); } }); stop=Button("停止",delegate { Stop(); });
            actions.Controls.Add(calibrate); actions.Controls.Add(start); actions.Controls.Add(stop);
            actions.Controls.Add(Button("開啟結果資料夾",delegate { string p=Path.Combine(Ocr.Root,"data","ocr"); Directory.CreateDirectory(p); Process.Start("explorer.exe",Ocr.Quote(p)); }));
            layout.Controls.Add(actions,0,2);
            var split=new TableLayoutPanel { Dock=DockStyle.Fill, ColumnCount=2, RowCount=2 };
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,48)); split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,52));
            split.RowStyles.Add(new RowStyle(SizeType.Absolute,30)); split.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            split.Controls.Add(new Label { Text="預覽：拖曳框選留言區，排除輸入框", AutoSize=true },0,0);
            split.Controls.Add(new Label { Text="最近一次 OCR 原文（未成立訂單）", AutoSize=true },1,0);
            split.Controls.Add(view,0,1); split.Controls.Add(output,1,1); layout.Controls.Add(split,0,3); layout.Controls.Add(status,0,4); Controls.Add(layout);
            windows.SelectedIndexChanged+=delegate { calibratedTarget=null; view.Selection=Rectangle.Empty; view.Invalidate(); UpdateButtons(); };
            view.SelectionChanged=delegate { UpdateButtons(); Say("框選完成："+view.Selection.Width+" × "+view.Selection.Height+"。按開始後，切回指定 LINE 社群。"); };
            timer.Tick+=async delegate { await Tick(); };
            FormClosing+=delegate(object sender,FormClosingEventArgs e) { if(busy) { e.Cancel=true; Say("正在保存這張畫面，請等候最多 30 秒後再關閉。"); } else Stop(); };
            if(!preview) RefreshWindows();
            Say("可先按「測試現有圖片」。即時監看只在指定 LINE 位於最前方時擷取。"); UpdateButtons();
        }
        private Button Button(string text, EventHandler action) { var b=new Button { Text=text, AutoSize=true, Height=34, Padding=new Padding(6,2,6,2) }; b.Click+=action; return b; }
        private void UpdateButtons() { refresh.Enabled=openFile.Enabled=windows.Enabled=!busy&&!monitoring; calibrate.Enabled=!busy&&!monitoring&&windows.SelectedItem!=null; start.Enabled=!busy&&!monitoring&&calibratedTarget!=null&&WindowCapture.Within(view.Selection,calibratedSize); stop.Enabled=monitoring; view.Enabled=!busy&&!monitoring; }
        private void Say(string text) { status.Text=journalError ?? text; }
        private void Event(string state) {
            if(session==null || state==lastEvent) return;
            try { File.AppendAllText(Path.Combine(session,"events.jsonl"),Ocr.Json.Serialize(new { AtUtc=DateTime.UtcNow.ToString("o"), State=state })+"\n",Ocr.Utf8); lastEvent=state; }
            catch(Exception ex) { monitoring=false; timer.Stop(); journalError="已停止：無法寫入監看紀錄。"+ex.Message; Say(journalError); UpdateButtons(); }
        }
        private void RefreshWindows() { windows.Items.Clear(); foreach(var t in WindowCapture.List()) windows.Items.Add(t); calibratedTarget=null; UpdateButtons(); Say("請選完整社群名稱；若只有 LINE 主視窗，先自行開啟獨立聊天室。"); }
        private async Task Calibrate() {
            var t=windows.SelectedItem as Target; if(t==null) return;
            if(String.Equals(t.Title.Trim(),"LINE",StringComparison.OrdinalIgnoreCase)) { Say("請先自行開啟獨立社群視窗，並選完整社群名稱；只叫 LINE 的主視窗無法核對聊天室。"); return; }
            busy=true; UpdateButtons(); calibratedTarget=null;
            try {
                for(int i=5;i>0;i--) { Say(i+" 秒後取得預覽，請現在切回「"+t.Title+"」。"); await Task.Delay(1000); }
                var bitmap=WindowCapture.Read(t,null,null); calibratedSize=bitmap.Size; calibratedTarget=t; view.SetImage(bitmap);
                Say("預覽已取得。回到此工具，在左側拖曳框選留言區，再按開始。");
            } catch(Exception ex) { Say(ex.Message); }
            finally { busy=false; UpdateButtons(); }
        }
        private void Start() {
            if(calibratedTarget==null || !WindowCapture.Within(view.Selection,calibratedSize)) return;
            journalError=null; roi=view.Selection; session=NewSession(); gate=new FrameGate(); frames=0; lastEvent=null;
            File.WriteAllText(Path.Combine(session,"session.json"),Ocr.Json.Serialize(new { Target=calibratedTarget, ClientWidth=calibratedSize.Width, ClientHeight=calibratedSize.Height, Region=new { roi.X,roi.Y,roi.Width,roi.Height }, IntervalMs=3000, CompletenessVerified=false, OrdersCreated=0 }),Ocr.Utf8);
            monitoring=true; Event("started"); if(!monitoring) return; timer.Start(); UpdateButtons(); Say("監看已開始，請切回指定社群。LINE 不在最前方時會暫停擷取。");
        }
        private void Stop() { monitoring=false; timer.Stop(); if(session!=null) Event("stopped"); UpdateButtons(); Say("已停止。辨識結果保存在本機；未建立正式訂單。"); }
        private static string NewSession() { string p=Path.Combine(Ocr.Root,"data","ocr",DateTime.Now.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,6)); Directory.CreateDirectory(p); return p; }
        private async Task Tick() {
            if(busy || !monitoring) return; busy=true; UpdateButtons();
            try {
                using(var bitmap=WindowCapture.Read(calibratedTarget,roi,calibratedSize)) {
                    string hash=Ocr.Hash(bitmap);
                    if(!gate.Changed(hash)) { Say("監看中：畫面未變，已略過重複截圖。已保存 "+frames+" 張變動畫面。"); Event("unchanged"); return; }
                    if(frames>=500) { Stop(); Say("本次已保存 500 張，已停止以限制磁碟用量。確認結果後可再開始。"); return; }
                    string prefix=Path.Combine(session,"frame-"+DateTime.Now.ToString("HHmmss-fff")); bitmap.Save(prefix+".png",ImageFormat.Png);
                    File.WriteAllText(prefix+".capture.json",Ocr.Json.Serialize(new { CapturedAtUtc=DateTime.UtcNow.ToString("o"), Target=calibratedTarget, Source="visible_screen_region", FrameHash=hash, CompletenessVerified=false, OrdersCreated=0 }),Ocr.Utf8);
                    Say("畫面有變化，正在本機辨識…");
                    try {
                        var result=await Task.Run(()=>Ocr.Run(prefix+".png",prefix)); gate.Commit(hash); frames++;
                        output.Text=Ocr.DisplayText(result.Text);
                        Event(String.IsNullOrWhiteSpace(result.Text)?"no_text":"recognized");
                        Say((monitoring?"監看中":"已停止")+"：已保存 "+frames+" 張；"+(String.IsNullOrWhiteSpace(result.Text)?"本張未辨識出文字。":"原文已保存，尚未核對為訂單。"));
                    } catch(Exception ex) { Stop(); Event("ocr_failed: "+ex.Message); Say("已停止："+ex.Message+" 原始截圖已保留。"); }
                }
            } catch(Exception ex) { Say(ex.Message); Event(ex.Message); }
            finally { busy=false; UpdateButtons(); }
        }
        private async Task LoadFile() {
            using(var dialog=new OpenFileDialog { Filter="圖片|*.png;*.jpg;*.jpeg;*.bmp", Title="選擇現有截圖：只讀這張圖片" }) {
                if(dialog.ShowDialog()!=DialogResult.OK) return; busy=true; UpdateButtons();
                try {
                    var image=new Bitmap(dialog.FileName); if(image.Width>10000 || image.Height>10000) { image.Dispose(); throw new Exception("圖片太大，請使用聊天室截圖。"); }
                    calibratedTarget=null; view.SetImage(image); string p=Path.Combine(NewSession(),"imported"); image.Save(p+".png",ImageFormat.Png);
                    Say("正在辨識選定圖片…"); var result=await Task.Run(()=>Ocr.Run(p+".png",p)); output.Text=Ocr.DisplayText(result.Text);
                    Say("圖片辨識完成。這是離線圖片測試，尚未驗證 LINE 即時監看。");
                } catch(Exception ex) { Say(ex.Message); }
                finally { busy=false; UpdateButtons(); }
            }
        }
        internal void Preview(string imagePath,string text,string outputPath) {
            view.SetImage(new Bitmap(imagePath)); view.Selection=new Rectangle(72,196,245,285); output.Text=text;
            Say("離線預覽：截圖 OCR 已有文字；訊息數量與完整性仍須核對。");
            ShowInTaskbar=false; Location=new Point(-20000,-20000); StartPosition=FormStartPosition.Manual;
            CreatePreviewHandles(this); PerformLayout();
            using(var bitmap=new Bitmap(Width,Height)) { DrawToBitmap(bitmap,new Rectangle(Point.Empty,Size)); bitmap.Save(outputPath,ImageFormat.Png); }
        }
        private static void CreatePreviewHandles(Control control) { var h=control.Handle; foreach(Control child in control.Controls) CreatePreviewHandles(child); control.PerformLayout(); }
    }

    internal static class Program
    {
        [STAThread] internal static int Main(string[] args) {
            try {
                WindowCapture.SetProcessDPIAware(); Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                if(args.Length==3 && args[0]=="--file") { string prefix=Path.GetFullPath(args[2]); Directory.CreateDirectory(Path.GetDirectoryName(prefix)); Ocr.Run(Path.GetFullPath(args[1]),prefix); return 0; }
                if(args.Length==3 && args[0]=="--preview") { using(var form=new MonitorForm(true)) form.Preview(args[1],"韓國麝香葡萄 PE 盒 出清價\r\n$ 200 / 盒 鬥\r\n生豆包 50 / 包 ( 5 入 )*6\r\n\r\n注意：數量符號可能誤判，請核對原圖。",args[2]); return 0; }
                if(args.Length==2 && args[0]=="--self-test") { SelfTest(args[1]); return 0; }
                if(args.Length!=0) throw new ArgumentException("Unknown arguments");
                Application.Run(new MonitorForm(false)); return 0;
            } catch(Exception ex) { if(args.Length>0) File.WriteAllText(Path.Combine(Ocr.Root,".qa","ocr-last-error.txt"),ex.ToString(),Ocr.Utf8); else MessageBox.Show(ex.Message,"OCR 工具"); return 1; }
        }
        private static void SelfTest(string path) {
            var results=new List<string>(); Action<bool,string> check=(value,label)=> { if(!value) throw new Exception("FAILED: "+label); results.Add(label); };
            var a=new Target { Handle=1, Pid=2, StartedUtc="a", Title="社群A" };
            check(WindowCapture.Same(a,new Target { Handle=1,Pid=2,StartedUtc="a",Title="社群A" }),"same target");
            check(!WindowCapture.Same(a,new Target { Handle=1,Pid=2,StartedUtc="a",Title="社群B" }),"reject changed chat title");
            check(!WindowCapture.Same(a,new Target { Handle=1,Pid=2,StartedUtc="b",Title="社群A" }),"reject reused process id");
            check(WindowCapture.Within(new Rectangle(0,0,100,100),new Size(100,100)),"ROI within client");
            check(!WindowCapture.Within(new Rectangle(-1,0,100,100),new Size(100,100)),"reject ROI outside client");
            check(!WindowCapture.Within(new Rectangle(0,0,10,100),new Size(100,100)),"reject empty or tiny ROI");
            var gate=new FrameGate(); check(gate.Changed("A"),"first frame read"); check(gate.Changed("A"),"failed OCR remains retryable"); gate.Commit("A"); check(!gate.Changed("A"),"skip consecutive identical frame"); gate.Commit("B"); check(gate.Changed("A"),"retain returning older frame; no global message dedup");
            check(Ocr.DisplayText("生 豆 包 + 1\r\n生 豆 包 + 1")=="生豆包 + 1\r\n生豆包 + 1","preserve identical separate text lines and quantity");
            using(var b=new Bitmap(100,100)) { string h=Ocr.Hash(b); b.SetPixel(25,25,Color.Red); check(h!=Ocr.Hash(b),"detect pixel changes"); }
            using(var region=new RegionView()) { region.Size=new Size(400,400); region.SetImage(new Bitmap(200,100)); check(region.ToImage(new Point(200,200))==new Point(100,50),"map letterboxed preview coordinates"); check(region.ToImage(new Point(400,400))==new Point(200,100),"clamp selection to image bounds"); }
            File.WriteAllText(path,Ocr.Json.Serialize(new { Passed=results.Count, Tests=results, LiveLineRead=false }),Ocr.Utf8);
        }
    }
}
