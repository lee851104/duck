using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Automation;
using System.Windows.Forms;
using LineOcrMonitor;

namespace LineExportMonitor
{
    internal static class ExportAutomation
    {
        [StructLayout(LayoutKind.Sequential)] private struct LastInput { public uint Size,Tick; }
        [StructLayout(LayoutKind.Sequential)] private struct MouseInput { public int X,Y; public uint Data,Flags,Time; public UIntPtr Extra; }
        [StructLayout(LayoutKind.Explicit)] private struct InputUnion { [FieldOffset(0)] public MouseInput Mouse; }
        [StructLayout(LayoutKind.Sequential)] private struct Input { public uint Type; public InputUnion Data; }
        [DllImport("user32.dll")] private static extern bool GetLastInputInfo(ref LastInput info);
        [DllImport("user32.dll")] private static extern bool SetCursorPos(int x,int y);
        [DllImport("user32.dll")] private static extern bool GetCursorPos(out WindowCapture.PointNative p);
        [DllImport("user32.dll")] private static extern uint SendInput(uint count,Input[] inputs,int size);
        [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr h,uint cmd);
        [DllImport("user32.dll")] private static extern IntPtr WindowFromPoint(WindowCapture.PointNative point);
        [DllImport("user32.dll")] private static extern IntPtr GetAncestor(IntPtr h,uint flags);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] private static extern int GetClassName(IntPtr h,StringBuilder s,int n);
        internal static uint IdleMilliseconds() { var i=new LastInput { Size=8 }; if(!GetLastInputInfo(ref i)) return 0; return unchecked((uint)Environment.TickCount-i.Tick); }
        private static bool OwnedBy(IntPtr h, Target target)
        {
            uint pid; WindowCapture.GetWindowThreadProcessId(h,out pid); if(pid!=target.Pid) return false;
            for(int i=0;i<12 && h!=IntPtr.Zero;i++,h=GetWindow(h,4)) if(h.ToInt64()==target.Handle) return true;
            return false;
        }
        internal static Rectangle Bounds(Target t,Size expected,bool menuAllowed)
        {
            var h=new IntPtr(t.Handle);
            if(!WindowCapture.Same(t,WindowCapture.Describe(h))) throw new Exception("LINE 社群視窗身分已改變。");
            var fg=WindowCapture.GetForegroundWindow();
            if(WindowCapture.IsIconic(h) || (fg!=h && !(menuAllowed && OwnedBy(fg,t)))) throw new Exception("LINE 已失去焦點；停止操作。");
            WindowCapture.Rect r; var p=new WindowCapture.PointNative();
            if(!WindowCapture.GetClientRect(h,out r) || !WindowCapture.ClientToScreen(h,ref p)) throw new Exception("無法定位 LINE。");
            var bounds=new Rectangle(p.X,p.Y,r.R-r.L,r.B-r.T);
            if(bounds.Size!=expected || !Screen.AllScreens.Any(s=>s.Bounds.Contains(bounds))) throw new Exception("LINE 尺寸或螢幕位置不符校準。");
            bool blocked=false,reached=false;
            WindowCapture.EnumWindows(delegate(IntPtr w,IntPtr x) {
                if(w==h) { reached=true; return false; }
                if(!WindowCapture.IsWindowVisible(w) || WindowCapture.IsIconic(w)) return true;
                int cloaked; if(WindowCapture.DwmGetWindowAttribute(w,14,out cloaked,4)==0 && cloaked!=0) return true;
                WindowCapture.Rect wr;
                if(WindowCapture.GetWindowRect(w,out wr) && bounds.IntersectsWith(Rectangle.FromLTRB(wr.L,wr.T,wr.R,wr.B)) && !(menuAllowed && OwnedBy(w,t))) { blocked=true; return false; }
                return true;
            },IntPtr.Zero);
            if(blocked || !reached) throw new Exception("有其他視窗遮住 LINE，停止操作。");
            return bounds;
        }
        private sealed class Shot : IDisposable {
            internal Bitmap Image; internal Rectangle Region; internal Rectangle TargetBounds;
            public void Dispose() { if(Image!=null)Image.Dispose(); }
        }
        private static Shot Screenshot(Target t,Size size)
        {
            var b=Bounds(t,size,true); Rectangle region=b;IntPtr popup=IntPtr.Zero;
            WindowCapture.EnumWindows(delegate(IntPtr h,IntPtr p) {
                if(h.ToInt64()==t.Handle)return false;
                if(WindowCapture.IsWindowVisible(h)&&!WindowCapture.IsIconic(h)&&OwnedBy(h,t)) {
                    WindowCapture.Rect r;if(WindowCapture.GetWindowRect(h,out r)) {var candidate=Rectangle.FromLTRB(r.L,r.T,r.R,r.B);if(candidate.Width>50&&candidate.Height>50){region=candidate;popup=h;return false;}}
                }
                return true;
            },IntPtr.Zero);
            if(!Screen.AllScreens.Any(s=>s.Bounds.Contains(region)))throw new Exception("LINE 選單超出螢幕範圍。");
            // A Qt popup may extend outside the chat window; capture that owned popup itself.
            bool blocked=false,reached=false;
            WindowCapture.EnumWindows(delegate(IntPtr h,IntPtr p) {
                if(h==(popup==IntPtr.Zero?new IntPtr(t.Handle):popup)){reached=true;return false;}
                int cloaked;if(WindowCapture.DwmGetWindowAttribute(h,14,out cloaked,4)==0&&cloaked!=0)return true;
                WindowCapture.Rect r;if(WindowCapture.IsWindowVisible(h)&&!WindowCapture.IsIconic(h)&&WindowCapture.GetWindowRect(h,out r)&&region.IntersectsWith(Rectangle.FromLTRB(r.L,r.T,r.R,r.B))){blocked=true;return false;}
                return true;
            },IntPtr.Zero);
            if(blocked||!reached)throw new Exception("選單上方有其他視窗，停止操作。");
            var image=new Bitmap(region.Width,region.Height);
            try { using(var g=Graphics.FromImage(image))g.CopyFromScreen(region.Location,Point.Empty,region.Size);if(Bounds(t,size,true)!=b)throw new Exception("LINE 擷取途中移動。");return new Shot{Image=image,Region=region,TargetBounds=b}; }
            catch{image.Dispose();throw;}
        }
        internal static Rectangle PatchBounds(Point p,Size size,int width,int height)
        {
            return Rectangle.Intersect(new Rectangle(Point.Empty,size),new Rectangle(p.X-width/2,p.Y-height/2,width,height));
        }
        internal static double Difference(Bitmap a,Bitmap b,Rectangle region)
        {
            if(a.Size!=b.Size || region.Width<1 || region.Height<1) return 255;
            double difference=0; int count=0;
            for(int y=region.Top;y<region.Bottom;y+=2) for(int x=region.Left;x<region.Right;x+=2) {
                var p=a.GetPixel(x,y); var q=b.GetPixel(x,y); difference+=Math.Abs(p.R-q.R)+Math.Abs(p.G-q.G)+Math.Abs(p.B-q.B); count+=3;
            }
            return difference/count;
        }
        private static Point Click(Target t,Size size,Point local,bool menuAllowed,CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); var b=Bounds(t,size,menuAllowed);
            if(!menuAllowed&&!new Rectangle(Point.Empty,size).Contains(local)) throw new Exception("操作位置超出視窗。");
            var point=new Point(b.X+local.X,b.Y+local.Y);
            var hit=GetAncestor(WindowFromPoint(new WindowCapture.PointNative{X=point.X,Y=point.Y}),2);
            if(hit!=new IntPtr(t.Handle)&&!(menuAllowed&&OwnedBy(hit,t)))throw new Exception("按鈕位置不屬於指定 LINE 視窗或其選單。");
            if(!SetCursorPos(point.X,point.Y)) throw new Exception("無法移動到已校準按鈕。");
            token.ThrowIfCancellationRequested(); if(Bounds(t,size,menuAllowed)!=b) throw new Exception("點擊前視窗已移動。");
            var inputs=new[] { new Input { Data=new InputUnion { Mouse=new MouseInput { Flags=2 } } },new Input { Data=new InputUnion { Mouse=new MouseInput { Flags=4 } } } };
            if(SendInput(2,inputs,Marshal.SizeOf(typeof(Input)))!=2) throw new Exception("滑鼠操作未完整送出，已停止。");
            return point;
        }
        private static void CheckCursor(Point expected) { WindowCapture.PointNative p; if(!GetCursorPos(out p) || p.X!=expected.X || p.Y!=expected.Y) throw new Exception("偵測到滑鼠移動，已停止自動操作。"); }
        internal sealed class Word { public string Text {get;set;} public double X {get;set;} public double Y {get;set;} public double Width {get;set;} public double Height {get;set;} }
        internal sealed class Line { public string Text {get;set;} public List<Word> Words {get;set;} }
        internal sealed class MenuOcr { public string Status {get;set;} public double Scale {get;set;} public List<Line> Lines {get;set;} }
        internal static Rectangle FindSaveLabel(string json,Size size,Point menu)
        {
            var ocr=ExportDelta.Json.Deserialize<MenuOcr>(json);
            if(ocr==null || ocr.Status!="recognized" || ocr.Scale<=0 || ocr.Lines==null) throw new Exception("選單辨識無效。");
            var found=ocr.Lines.Where(l=>Regex.Replace(l.Text ?? "",@"\s+","")=="儲存聊天" && l.Words!=null && l.Words.Count>0).ToList();
            if(found.Count!=1) throw new Exception("未唯一找到「儲存聊天」；不嘗試猜測點擊位置。");
            var words=found[0].Words;
            int x=(int)Math.Floor(words.Min(w=>w.X)/ocr.Scale),y=(int)Math.Floor(words.Min(w=>w.Y)/ocr.Scale);
            int right=(int)Math.Ceiling(words.Max(w=>w.X+w.Width)/ocr.Scale),bottom=(int)Math.Ceiling(words.Max(w=>w.Y+w.Height)/ocr.Scale);
            var rect=Rectangle.FromLTRB(x,y,right,bottom);
            if(!new Rectangle(Point.Empty,size).Contains(rect) || rect.Width<20 || rect.Height<8 || rect.Y<=menu.Y) throw new Exception("「儲存聊天」不在預期選單區域，已停止。");
            return rect;
        }
        private static bool DialogTitle(string title) { return Regex.IsMatch(title ?? "", "儲存|另存|保存|Save",RegexOptions.IgnoreCase); }
        private static IntPtr FindSaveDialog(Target target)
        {
            var h=WindowCapture.GetForegroundWindow(); var cls=new StringBuilder(256); GetClassName(h,cls,cls.Capacity);
            return cls.ToString()=="#32770" && OwnedBy(h,target) && DialogTitle(WindowCapture.Title(h)) ? h:IntPtr.Zero;
        }
        private static void FillAndSave(IntPtr handle,Target target,string file,CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); if(FindSaveDialog(target)!=handle) throw new Exception("儲存視窗已改變，未輸入檔名。");
            var root=AutomationElement.FromHandle(handle);
            var edits=root.FindAll(TreeScope.Descendants,new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Edit)).Cast<AutomationElement>()
                .Where(e=>e.Current.AutomationId=="1001" || e.Current.AutomationId=="1148").ToList();
            var buttons=root.FindAll(TreeScope.Descendants,new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Button)).Cast<AutomationElement>()
                .Where(e=>e.Current.AutomationId=="1" && DialogTitle(e.Current.Name)).ToList();
            if(edits.Count!=1 || buttons.Count!=1) throw new Exception("不支援這個儲存對話框，已停止；不會把檔名輸入聊天室。");
            object value,invoke;
            if(!edits[0].TryGetCurrentPattern(ValuePattern.Pattern,out value) || !buttons[0].TryGetCurrentPattern(InvokePattern.Pattern,out invoke)) throw new Exception("儲存對話框未提供可用控制項。");
            token.ThrowIfCancellationRequested(); if(FindSaveDialog(target)!=handle) throw new Exception("儲存視窗已失去焦點。");
            ((ValuePattern)value).SetValue(file);
            token.ThrowIfCancellationRequested(); if(FindSaveDialog(target)!=handle || ((ValuePattern)value).Current.Value!=file) throw new Exception("檔名核對失敗，已停止。");
            ((InvokePattern)invoke).Invoke();
        }
        internal static async Task<string> Save(Target target,Bitmap calibration,Point menu,string work,CancellationToken token,Action<string> status)
        {
            Directory.CreateDirectory(work); Size size=calibration.Size;
            using(var current=WindowCapture.Read(target,null,size)) if(Difference(calibration,current,PatchBounds(menu,size,28,28))>10) throw new Exception("選單按鈕外觀已改變，請重新校準。");
            if(IdleMilliseconds()<5000) throw new Exception("使用者仍在操作電腦，已停止這次自動儲存。");
            status("開啟 LINE 選單…"); Point pointer=Click(target,size,menu,false,token); await Task.Delay(700,token);
            string prefix=Path.Combine(work,"last-menu");
            using(var screen=Screenshot(target,size)) {
                screen.Image.Save(prefix+".png",ImageFormat.Png); CheckCursor(pointer);
                status("核對「儲存聊天」按鈕…"); await Task.Run(()=>Ocr.Run(prefix+".png",prefix));
                token.ThrowIfCancellationRequested(); CheckCursor(pointer);
                var relativeMenu=new Point(screen.TargetBounds.X+menu.X-screen.Region.X,screen.TargetBounds.Y+menu.Y-screen.Region.Y);
                var label=FindSaveLabel(File.ReadAllText(prefix+".ocr.json",ExportDelta.Utf8),screen.Image.Size,relativeMenu);
                var local=new Point(screen.Region.X+label.X+label.Width/2-screen.TargetBounds.X,screen.Region.Y+label.Y+label.Height/2-screen.TargetBounds.Y);
                if(local.X<size.Width/2||local.Y<=menu.Y)throw new Exception("儲存按鈕不在右側選單區域。");
                using(var fresh=Screenshot(target,size)) if(fresh.Region!=screen.Region||fresh.TargetBounds!=screen.TargetBounds||Difference(screen.Image,fresh.Image,label)>5) throw new Exception("選單內容在辨識期間改變，已停止。");
                pointer=Click(target,size,local,true,token);
            }
            IntPtr dialog=IntPtr.Zero;
            for(int i=0;i<32;i++) { await Task.Delay(250,token); CheckCursor(pointer); dialog=FindSaveDialog(target); if(dialog!=IntPtr.Zero) break; }
            if(dialog==IntPtr.Zero) throw new Exception("未找到屬於此社群的標準儲存視窗；請手動檢查。這版不猜測其他對話框。");
            string path=Path.Combine(work,"incoming-"+Guid.NewGuid().ToString("N")+".txt");
            status("儲存聊天文字檔…"); await Task.Run(()=>FillAndSave(dialog,target,path,token));
            string previous=null; int stable=0;
            for(int i=0;i<60;i++) {
                await Task.Delay(500,token);
                if(!File.Exists(path) || WindowCapture.IsWindowVisible(dialog)) continue;
                try {
                    byte[] bytes; using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.None)) { if(stream.Length>30000000) throw new Exception("匯出檔超過 30 MB。"); bytes=new byte[(int)stream.Length]; int offset=0,n; while(offset<bytes.Length && (n=stream.Read(bytes,offset,bytes.Length-offset))>0) offset+=n; if(offset!=bytes.Length) continue; }
                    string hash;using(var sha=System.Security.Cryptography.SHA256.Create())hash=Convert.ToBase64String(sha.ComputeHash(bytes));
                    stable=hash==previous ? stable+1:0; previous=hash;
                    if(bytes.Length>0 && stable>=3) return path;
                } catch(IOException) { }
            }
            throw new Exception("匯出檔尚未完成寫入，已保留檔案並停止。");
        }
        internal static void RemoveSuccessfulInput(string file,string work)
        {
            string root=Path.GetFullPath(work).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
            string path=Path.GetFullPath(file);
            if(!path.StartsWith(root,StringComparison.OrdinalIgnoreCase) || !Regex.IsMatch(Path.GetFileName(path),@"^incoming-[0-9a-f]{32}\.txt$")) throw new Exception("拒絕刪除不屬於工具的匯出檔。");
            File.Delete(path);
        }
    }
}
