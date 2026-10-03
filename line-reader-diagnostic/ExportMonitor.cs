using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using LineOcrMonitor;

namespace LineExportMonitor
{
    internal sealed class ExportForm : Form
    {
        private ComboBox windows=new ComboBox { DropDownStyle=ComboBoxStyle.DropDownList,Width=550 };
        private RegionView view=new RegionView { Dock=DockStyle.Fill };
        private TextBox output=new TextBox { Dock=DockStyle.Fill,Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Both,WordWrap=false };
        private Label status=new Label { Dock=DockStyle.Fill,ForeColor=Color.DarkBlue };
        private Label baselineLabel=new Label { AutoSize=true,Text="初次啟動：選一份已匯出的聊天檔作為基準。" };
        private Button refresh,preview,mark,start,stop,baseline,manual;
        private System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer { Interval=2000 };
        private Target target;
        private Rectangle roi;
        private Point? menu;
        private string initialFile,observed,handled,work;
        private int stable;
        private bool busy,running,marking,force;
        private CancellationTokenSource cancel;
        private DeltaStore store;
        private DateTime lastExport=DateTime.MinValue;
        private DateTime pendingSince=DateTime.MinValue;
        internal ExportForm(bool offline)
        {
            Text="LINE 新留言匯出 v0.1 — 文字檔比對"; Width=1140;Height=850;MinimumSize=new Size(1050,720);Font=new Font("Microsoft JhengHei UI",10);StartPosition=FormStartPosition.CenterScreen;
            var layout=new TableLayoutPanel { Dock=DockStyle.Fill,Padding=new Padding(12),ColumnCount=1,RowCount=6 };
            foreach(float height in new[]{60f,44f,38f,44f}) layout.RowStyles.Add(new RowStyle(SizeType.Absolute,height));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent,100)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute,70));
            layout.Controls.Add(new Label { Dock=DockStyle.Fill,Text="新留言匯出｜只輸出新增內容\n畫面變化觸發儲存，再以文字檔確認新增；電腦需閒置 5 秒，LINE 保持最前方。" },0,0);
            var row1=new FlowLayoutPanel { Dock=DockStyle.Fill,WrapContents=false }; row1.Controls.Add(windows);
            refresh=B("重新整理",delegate { Refresh(); }); baseline=B("選擇基準檔",delegate { PickBaseline(); }); row1.Controls.Add(refresh);row1.Controls.Add(baseline);layout.Controls.Add(row1,0,1);
            layout.Controls.Add(baselineLabel,0,2);
            var row2=new FlowLayoutPanel { Dock=DockStyle.Fill,WrapContents=false };
            preview=B("1. 取得預覽（5秒）",async delegate { await Calibrate(); });mark=B("2. 標記右上 ⋮",delegate { marking=true; Say("在預覽上點選右上角的 ⋮ 選單鈕，勿選其他按鈕。"); });
            start=B("3. 開始監看",delegate { Begin(); });stop=B("停止",delegate { Stop(); });manual=B("比對手動匯出檔",delegate { Manual(); });
            foreach(var b in new[]{preview,mark,start,stop,manual}) row2.Controls.Add(b);
            row2.Controls.Add(B("結果資料夾",delegate { string root=store==null?Path.Combine(Ocr.Root,"data","export-monitor"):store.Root;Directory.CreateDirectory(root);Process.Start("explorer.exe",Ocr.Quote(root)); }));
            layout.Controls.Add(row2,0,3);
            var split=new TableLayoutPanel { Dock=DockStyle.Fill,ColumnCount=2,RowCount=2 };
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,48)); split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,52)); split.RowStyles.Add(new RowStyle(SizeType.Absolute,30));split.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            split.Controls.Add(new Label { Text="拖曳框選訊息區，排除公告與輸入框",AutoSize=true },0,0);split.Controls.Add(new Label { Text="本次新增留言（保留原文，尚未成立訂單）",AutoSize=true },1,0);split.Controls.Add(view,0,1);split.Controls.Add(output,1,1);layout.Controls.Add(split,0,4);layout.Controls.Add(status,0,5);Controls.Add(layout);
            windows.SelectedIndexChanged+=delegate { target=null;menu=null;store=null;roi=Rectangle.Empty;Buttons(); };
            view.SelectionChanged=delegate { if(!marking) { roi=view.Selection;Say("訊息區已框選；再標記右上角 ⋮ 按鈕。"); }Buttons(); };
            view.MouseClick+=delegate(object sender,MouseEventArgs e) {
                if(!marking || view.Image==null || !view.ImageRect.Contains(e.Location)) return;
                var p=view.ToImage(e.Location);
                if(p.X<view.Image.Width*0.65 || p.Y>view.Image.Height*0.25) { Say("請標記預覽右上角的 ⋮ 選單鈕。");return; }
                menu=p;marking=false;view.Selection=roi;view.Invalidate();Buttons();Say("選單鈕已標記。確認藍框只包含訊息區，按開始後切回 LINE。");
            };
            view.Paint+=delegate(object sender,PaintEventArgs e) { if(menu.HasValue && view.Image!=null) { var r=view.ImageRect;float x=r.X+menu.Value.X*r.Width/view.Image.Width,y=r.Y+menu.Value.Y*r.Height/view.Image.Height;using(var pen=new Pen(Color.LimeGreen,3))e.Graphics.DrawEllipse(pen,x-8,y-8,16,16); } };
            timer.Tick+=async delegate { await Tick(); };
            FormClosing+=delegate(object sender,FormClosingEventArgs e) { Stop();if(busy) { e.Cancel=true;Say("已要求停止；正在等候本次工作退出，稍後可關閉。"); } };
            if(!offline) {
                string known=Path.Combine(Ocr.Root,"..","[LINE]菜騎鴨-生鮮蔬果冷凍食品南北雜貨.txt");
                if(File.Exists(known)) {initialFile=Path.GetFullPath(known);baselineLabel.Text="首次基準："+Path.GetFileName(initialFile)+"（原檔保留）";}
                Refresh();
            }
            Buttons();Say("初次只建立比對基準；之後只輸出新增留言。原始聊天檔不會被刪除。");
        }
        private Button B(string text,EventHandler action) { var b=new Button { Text=text,AutoSize=true,Height=34,Padding=new Padding(4,2,4,2) };b.Click+=action;return b; }
        private void Buttons() {
            bool idle=!busy&&!running;refresh.Enabled=baseline.Enabled=windows.Enabled=idle;preview.Enabled=idle&&windows.SelectedItem!=null;mark.Enabled=idle&&target!=null&&view.Image!=null;manual.Enabled=idle&&windows.SelectedItem!=null;
            start.Enabled=idle&&target!=null&&menu.HasValue&&view.Image!=null&&WindowCapture.Within(roi,view.Image.Size);stop.Enabled=running||busy;view.Enabled=idle;
        }
        private void Say(string s) { status.Text=s; }
        private new void Refresh() { windows.Items.Clear();foreach(var t in WindowCapture.List())windows.Items.Add(t);target=null;menu=null;store=null;Buttons(); }
        private void PickBaseline() { using(var d=new OpenFileDialog { Filter="LINE 聊天文字檔|*.txt" }) if(d.ShowDialog()==DialogResult.OK) {initialFile=d.FileName;baselineLabel.Text="首次基準："+Path.GetFileName(initialFile)+"（既有比對進度不會重設）";} }
        private void OpenStore(Target selected) {
            string folder=Path.Combine(Ocr.Root,"data","export-monitor",ExportDelta.Hash(selected.Title).Substring(0,16));store=new DeltaStore(folder);work=Path.Combine(folder,"work");Directory.CreateDirectory(work);
            if(store.State==null) { if(initialFile==null)throw new Exception("請先選擇一份這個社群的聊天檔作為基準。");store.Initialize(initialFile,selected.Title); }
            if(store.State.TargetTitle!=selected.Title)throw new Exception("基準的社群名稱不符。");
            baselineLabel.Text="比對基準："+store.State.Entries.Count+" 筆記錄，最後日期 "+store.State.Entries.Last().Date+"；重啟後沿用。";
        }
        private async Task Calibrate() {
            var selected=windows.SelectedItem as Target;if(selected==null)return;
            if(selected.Title.Trim().Equals("LINE",StringComparison.OrdinalIgnoreCase)) {Say("請選擇具有完整社群標題的獨立視窗。");return;}
            busy=true;Buttons();cancel=new CancellationTokenSource();var token=cancel.Token;
            try {
                for(int i=5;i>0;i--) {Say(i+" 秒後取得預覽：請關閉 LINE 選單，切回指定社群，滑鼠移開右上選單鈕。");await Task.Delay(1000,token);}
                var bitmap=WindowCapture.Read(selected,null,null);target=selected;menu=null;roi=Rectangle.Empty;view.SetImage(bitmap);Say("預覽已取得：拖曳框選訊息區，接著按「標記右上 ⋮」。");
            }catch(OperationCanceledException){Say("已取消校準。");}catch(Exception ex){Say(ex.Message);}finally{busy=false;Buttons();}
        }
        private void Begin() {
            try {
                OpenStore(target);
                if(Directory.GetFiles(work,"incoming-*.txt").Length>0)throw new Exception("上次有待核對的完整匯出檔留在 work；先用「比對手動匯出檔」核對，避免跳過它。");
                cancel=new CancellationTokenSource();running=true;force=true;observed=handled=null;stable=0;pendingSince=DateTime.MinValue;timer.Start();Buttons();Say("已開始，請切回 LINE 並停止操作滑鼠鍵盤 5 秒。第一次會先匯出追上基準後的新留言。");
            }catch(Exception ex){Say(ex.Message);}
        }
        private void Stop() {running=false;timer.Stop();if(cancel!=null)cancel.Cancel();Buttons();Say("已停止自動操作。已保存的新增留言仍在結果資料夾。");}
        private void Log(string state) {if(store!=null) File.AppendAllText(Path.Combine(store.Root,"events.jsonl"),ExportDelta.Json.Serialize(new {AtUtc=DateTime.UtcNow.ToString("o"),State=state})+"\n",ExportDelta.Utf8);}
        private async Task Tick() {
            if(busy||!running)return;busy=true;Buttons();bool operating=false;
            try {
                if(ExportAutomation.IdleMilliseconds()<5000){Say("等待電腦閒置 5 秒；目前不操作 LINE。");return;}
                string hash;using(var image=WindowCapture.Read(target,roi,view.Image.Size))hash=Ocr.Hash(image);
                stable=hash==observed?stable+1:0;observed=hash;
                if(!force && hash==handled){pendingSince=DateTime.MinValue;Say("監看中：聊天區未變化。");return;}
                if(pendingSince==DateTime.MinValue)pendingSince=DateTime.UtcNow;
                if(stable<1&&(DateTime.UtcNow-pendingSince).TotalSeconds<10){Say("偵測到畫面變化，等待畫面穩定（最多 10 秒）…");return;}
                if((DateTime.UtcNow-lastExport).TotalSeconds<10){Say("等待儲存間隔，避免連續下載。");return;}
                operating=true;Log("export_started");
                string file=await ExportAutomation.Save(target,view.Image,menu.Value,work,cancel.Token,Say);
                var result=store.Apply(file);
                if(result.Status!="matched") {Stop();Log("review_required: "+result.Reason);Say("已停止："+result.Reason+" 完整匯出檔保留在 work。");return;}
                ExportAutomation.RemoveSuccessfulInput(file,work);lastExport=DateTime.UtcNow;handled=hash;force=false;pendingSince=DateTime.MinValue;
                output.Text=result.Added.Count==0?"本次沒有新增留言，未建立新批次。":ExportDelta.Render(result.Added);
                Log("added_entries="+result.Added.Count);Say("本次新增 "+result.Added.Count+" 筆記錄；重複部分未輸出，完整暫存匯出檔已清除。繼續監看。");
            }catch(OperationCanceledException){Say("已停止後續點擊；若已匯出檔案，會保留供下次核對。");}
            catch(Exception ex){if(operating){Stop();try{Log("failed: "+ex.Message);}catch{}Say("已停止："+ex.Message);}else Say("暫停偵測："+ex.Message);}
            finally{busy=false;Buttons();}
        }
        private void Manual() {
            try {
                var selected=windows.SelectedItem as Target;OpenStore(selected);
                using(var d=new OpenFileDialog {Filter="LINE 聊天文字檔|*.txt"}) {
                    if(d.ShowDialog()!=DialogResult.OK)return;var result=store.Apply(d.FileName);
                    if(result.Status!="matched"){Say("待人工核對："+result.Reason);return;}
                    if(Path.GetFullPath(Path.GetDirectoryName(d.FileName)).Equals(Path.GetFullPath(work),StringComparison.OrdinalIgnoreCase) && System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(d.FileName),@"^incoming-[0-9a-f]{32}\.txt$")) ExportAutomation.RemoveSuccessfulInput(d.FileName,work);
                    output.Text=ExportDelta.Render(result.Added);Say("手動匯出檔比對完成：新增 "+result.Added.Count+" 筆。工具外的原始檔保留。");
                }
            }catch(Exception ex){Say(ex.Message);}
        }
        internal void RenderPreview(string image,string destination) {
            windows.Items.Add(new Target {Title="版面測試社群（模擬資料）",Pid=123});windows.SelectedIndex=0;
            view.SetImage(new Bitmap(image));roi=new Rectangle(50,160,300,380);view.Selection=roi;menu=new Point(419,44);
            output.Text="2026-10-03\r\n10:05 測試客人 葡萄 +1\r\n10:05 測試客人 葡萄 +1\r\n\r\n相同文字的兩次追加會各自保留。";
            Say("離線版面預覽；未操作 LINE。匯出文字檔比對已驗證，即時儲存仍待測試。");
            Handles(this);PerformLayout();using(var bitmap=new Bitmap(Width,Height)){DrawToBitmap(bitmap,new Rectangle(Point.Empty,Size));bitmap.Save(destination,System.Drawing.Imaging.ImageFormat.Png);}
        }
        private static void Handles(Control c){var h=c.Handle;foreach(Control child in c.Controls)Handles(child);c.PerformLayout();}
    }
    internal static class ExportProgram
    {
        [STAThread] internal static int Main(string[] args) {
            try {
                WindowCapture.SetProcessDPIAware();Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
                if(args.Length==3&&args[0]=="--self-test"){ExportTests.Run(args[1],args[2]);return 0;}
                if(args.Length==3&&args[0]=="--preview"){using(var f=new ExportForm(true))f.RenderPreview(args[1],args[2]);return 0;}
                if(args.Length!=0)throw new Exception("Unknown arguments");
                bool owned;using(var mutex=new Mutex(true,"Local\\LineExportMonitor-"+ExportDelta.Hash(Ocr.Root).Substring(0,16),out owned)){if(!owned){MessageBox.Show("匯出工具已啟動，請使用現有視窗。");return 1;}Application.Run(new ExportForm(false));}
                return 0;
            }catch(Exception ex){if(args.Length>0){Directory.CreateDirectory(Path.Combine(Ocr.Root,".qa"));File.WriteAllText(Path.Combine(Ocr.Root,".qa","export-error.txt"),ex.ToString(),ExportDelta.Utf8);}else MessageBox.Show(ex.Message,"LINE 匯出工具");return 1;}
        }
    }
}
