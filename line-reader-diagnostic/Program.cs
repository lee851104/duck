using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Automation;
using System.Windows.Forms;

namespace LineReaderDiagnostic
{
    public sealed class WindowInfo
    {
        public long Handle;
        public int ProcessId;
        public string ProcessStartedUtc;
        public string Title;
        public bool Minimized;
        public override string ToString() { return Title + "  [PID " + ProcessId + "]" + (Minimized ? "（最小化）" : ""); }
    }

    public sealed class NodeInfo
    {
        public int Index;
        public int Parent;
        public int Depth;
        public string ControlType;
        public string Name;
        public string AutomationId;
        public string ClassName;
        public string FrameworkId;
        public bool Offscreen;
        public bool Skipped;
        public string Text;
        public string Value;
        public string HelpText;
        public string ItemStatus;
        public List<string> SupportedPatterns = new List<string>();
        public string TextReadPolicy;
        public bool? ValuePatternIsReadOnly;
        public string ValueReadPolicy;
        public bool TextTruncated;
        public List<string> Errors = new List<string>();
    }

    public sealed class Report
    {
        public string Format = "line-uia-diagnostic-v2.1";
        public string CapturedAtUtc = DateTime.UtcNow.ToString("o");
        public string Status = "not_started";
        public WindowInfo Target;
        public bool MessageCompletenessVerified = false;
        public bool UiTreeTraversalCompleted;
        public string MsaaStatus = "not_started";
        public string MsaaError;
        public List<MsaaNode> MsaaNodes = new List<MsaaNode>();
        public int MaxNodes = 600;
        public int MaxDepth = 24;
        public int MaxTextChars = 16000;
        public List<NodeInfo> Nodes = new List<NodeInfo>();
        public List<string> Notes = new List<string>();
        public string Error;
    }

    internal static class Native
    {
        internal delegate bool EnumProc(IntPtr hwnd, IntPtr parameter);
        [DllImport("user32.dll")] internal static extern bool EnumWindows(EnumProc callback, IntPtr parameter);
        [DllImport("user32.dll")] internal static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern bool IsWindow(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern bool IsIconic(IntPtr hwnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder value, int count);
        [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
        internal static string Title(IntPtr hwnd)
        {
            var buffer = new StringBuilder(4096);
            GetWindowText(hwnd, buffer, buffer.Capacity);
            return buffer.ToString();
        }
        internal static List<WindowInfo> ListLineWindows()
        {
            var result = new List<WindowInfo>();
            EnumProc callback = delegate(IntPtr hwnd, IntPtr parameter)
            {
                if (!IsWindowVisible(hwnd)) return true;
                uint pid;
                GetWindowThreadProcessId(hwnd, out pid);
                try
                {
                    using (var process = Process.GetProcessById((int)pid))
                    {
                        if (!String.Equals(process.ProcessName, "LINE", StringComparison.OrdinalIgnoreCase)) return true;
                        string title = Title(hwnd);
                        if (String.IsNullOrWhiteSpace(title)) return true;
                        result.Add(new WindowInfo { Handle = hwnd.ToInt64(), ProcessId = (int)pid,
                            ProcessStartedUtc = process.StartTime.ToUniversalTime().ToString("o"),
                            Title = title, Minimized = IsIconic(hwnd) });
                    }
                }
                catch (ArgumentException) { }
                catch (System.ComponentModel.Win32Exception) { }
                catch (InvalidOperationException) { }
                return true;
            };
            if (!EnumWindows(callback, IntPtr.Zero)) throw new InvalidOperationException("無法列出視窗。");
            return result;
        }
        internal static void Validate(WindowInfo expected)
        {
            var hwnd = new IntPtr(expected.Handle);
            uint pid;
            if (!IsWindow(hwnd)) throw new InvalidOperationException("指定視窗已關閉，請重新整理視窗清單。");
            GetWindowThreadProcessId(hwnd, out pid);
            using (var process = Process.GetProcessById((int)pid))
            {
                if (!Program.SameTarget(expected, new WindowInfo { Handle = hwnd.ToInt64(), ProcessId = (int)pid,
                    ProcessStartedUtc = process.StartTime.ToUniversalTime().ToString("o"), Title = Title(hwnd) }) ||
                    !String.Equals(process.ProcessName, "LINE", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("視窗身分或標題已改變。已停止讀取，請重新選擇。");
            }
        }
    }

    internal static class Reader
    {
        private sealed class Work { internal AutomationElement Element; internal int Parent; internal int Depth; }
        internal static Report Read(WindowInfo target)
        {
            var report = new Report { Target = target, Status = "reading" };
            report.Notes.Add("這是 UI Automation 元件快照，不是 LINE 訊息 API；未驗證整串留言完整性。");
            report.Notes.Add("Name 可能是按鈕或標籤；父子元件可能重複提供文字，不能把每個元件視為一則訊息。");
            report.Notes.Add("未展開或未載入的串文可能不存在於這份快照；未取得的作者、時間與訊息 ID 不會補猜。");
            try
            {
                Native.Validate(target);
                if (Native.IsIconic(new IntPtr(target.Handle)))
                {
                    report.Status = "minimized";
                    report.Error = "請自行還原 LINE 視窗，再重新讀取。程式不會替你切換視窗。";
                    return report;
                }
                AutomationElement root = AutomationElement.FromHandle(new IntPtr(target.Handle));
                if (root == null) throw new InvalidOperationException("沒有取得 UI Automation 視窗元件。");
                var queue = new Queue<Work>();
                queue.Enqueue(new Work { Element = root, Parent = -1, Depth = 0 });
                var clock = Stopwatch.StartNew();
                var walker = TreeWalker.RawViewWalker;
                bool limited = false;
                bool errors = false;
                while (queue.Count > 0)
                {
                    if (clock.Elapsed.TotalSeconds > 30 || report.Nodes.Count >= report.MaxNodes)
                    {
                        limited = true;
                        report.Notes.Add("已達讀取時間或元件數上限，結果只有部分內容。");
                        break;
                    }
                    Native.Validate(target);
                    Work item = queue.Dequeue();
                    var node = new NodeInfo { Index = report.Nodes.Count, Parent = item.Parent, Depth = item.Depth };
                    report.Nodes.Add(node);
                    try
                    {
                        var info = item.Element.Current;
                        node.ControlType = info.ControlType.ProgrammaticName;
                        node.Offscreen = info.IsOffscreen;
                        node.ClassName = info.ClassName;
                        // Skip editable/password subtrees; no Value setters or input patterns exist in this reader.
                        node.Skipped = Program.SkipControl(node.ControlType, info.IsPassword, node.ClassName);
                        if (node.Skipped) continue;
                        node.Name = Program.Clip(info.Name, report.MaxTextChars, node);
                        node.AutomationId = Program.Clip(info.AutomationId, 2000, node);
                        node.ClassName = Program.Clip(info.ClassName, 2000, node);
                        node.FrameworkId = info.FrameworkId;
                        node.HelpText = Program.Clip(info.HelpText, report.MaxTextChars, node);
                        node.ItemStatus = Program.Clip(info.ItemStatus, report.MaxTextChars, node);
                        try { node.SupportedPatterns.AddRange(item.Element.GetSupportedPatterns().Select(p => p.ProgrammaticName)); }
                        catch (Exception ex) { node.Errors.Add("SupportedPatterns: " + ex.GetType().Name); }
                        object pattern;
                        // A LINE text/message control may be a Group, ListItem, or Custom control.
                        // Read TextPattern only when the provider explicitly reports a read-only range.
                        if (Program.ReadTextPattern(node.ControlType))
                        {
                            try
                            {
                                if (item.Element.TryGetCurrentPattern(TextPattern.Pattern, out pattern))
                                {
                                    var range = ((TextPattern)pattern).DocumentRange;
                                    object readOnly = range.GetAttributeValue(TextPattern.IsReadOnlyAttribute);
                                    if (Program.IsExplicitlyReadOnly(readOnly))
                                    {
                                        node.TextReadPolicy = "read_only_range";
                                        node.Text = Program.Clip(range.GetText(report.MaxTextChars + 1), report.MaxTextChars, node);
                                    }
                                    else node.TextReadPolicy = "skipped_editable_mixed_or_unknown_range";
                                }
                                else node.TextReadPolicy = "text_pattern_not_supported";
                            }
                            catch (Exception ex) { node.Errors.Add("TextPattern: " + ex.GetType().Name); }
                            try
                            {
                                if (item.Element.TryGetCurrentPattern(ValuePattern.Pattern, out pattern))
                                {
                                    var value = ((ValuePattern)pattern).Current;
                                    node.ValuePatternIsReadOnly = value.IsReadOnly;
                                    if (Program.CanReadValue(node.ControlType, node.ClassName, value.IsReadOnly))
                                    {
                                        node.ValueReadPolicy = value.IsReadOnly ? "read_readonly_value" : "read_label_or_listitem_getter_only";
                                        node.Value = Program.Clip(value.Value, report.MaxTextChars, node);
                                    }
                                    else node.ValueReadPolicy = "skipped_non_readonly_container";
                                }
                                else node.ValueReadPolicy = "value_pattern_not_supported";
                            }
                            catch (Exception ex) { node.Errors.Add("ValuePattern: " + ex.GetType().Name); }
                        }
                        if (node.Errors.Count > 0) errors = true;
                        AutomationElement child = walker.GetFirstChild(item.Element);
                        if (child != null && item.Depth >= report.MaxDepth)
                        {
                            limited = true;
                            report.Notes.Add("部分元件超過深度上限，未繼續展開。");
                            continue;
                        }
                        while (child != null)
                        {
                            if (report.Nodes.Count + queue.Count >= report.MaxNodes || clock.Elapsed.TotalSeconds > 30)
                            {
                                limited = true;
                                break;
                            }
                            queue.Enqueue(new Work { Element = child, Parent = node.Index, Depth = item.Depth + 1 });
                            child = walker.GetNextSibling(child);
                        }
                    }
                    catch (Exception ex)
                    {
                        errors = true;
                        node.Errors.Add(ex.GetType().Name + ": " + ex.Message);
                    }
                }
                Native.Validate(target);
                if (limited) report.Notes.Add("有內容因元件數、深度或時間限制未讀取。");
                if (report.Nodes.Any(n => n.TextTruncated))
                {
                    limited = true;
                    report.Notes.Add("有文字超過字數上限，已截短並在元件標記。");
                }
                report.UiTreeTraversalCompleted = !limited && !errors;
                report.Status = limited || errors ? "partial" : "snapshot_ready";
                if (!report.Nodes.Any(n => !n.Skipped && n.Depth > 0 &&
                    (!String.IsNullOrWhiteSpace(n.Name) || !String.IsNullOrWhiteSpace(n.Text) || !String.IsNullOrWhiteSpace(n.Value))))
                    report.Notes.Add("沒有讀到子元件文字；這不代表社群沒有訊息，也不代表所有讀取方式都不可用。");
            }
            catch (Exception ex)
            {
                report.Status = "failed";
                report.UiTreeTraversalCompleted = false;
                report.Error = ex.GetType().Name + ": " + ex.Message;
            }
            return report;
        }
    }

    internal static class Program
    {
        internal static readonly Encoding Utf8 = new UTF8Encoding(true);
        internal static JavaScriptSerializer Serializer() { return new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024 }; }
        internal static string Root { get { return Directory.GetParent(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)).FullName; } }
        internal static bool SameTarget(WindowInfo a, WindowInfo b)
        {
            return a != null && b != null && a.Handle == b.Handle && a.ProcessId == b.ProcessId &&
                String.Equals(a.ProcessStartedUtc, b.ProcessStartedUtc, StringComparison.Ordinal) &&
                String.Equals(a.Title, b.Title, StringComparison.Ordinal);
        }
        internal static bool SkipControl(string type, bool password, string className = null)
        { return password || type == "ControlType.Edit" || className == "MessageInputPanel"; }
        internal static bool ReadTextPattern(string type) { return type != "ControlType.Window" && type != "ControlType.Edit"; }
        internal static bool IsExplicitlyReadOnly(object value) { return value is bool && (bool)value; }
        internal static bool CanReadValue(string type, string className, bool readOnly)
        {
            if (type == "ControlType.Window" || SkipControl(type, false, className)) return false;
            // IsReadOnly describes whether the provider accepts a setter; reading Value is a getter.
            // Limit the exception to text labels and list items, preserving input-subtree exclusions.
            return readOnly || className == "LcText" || type == "ControlType.Text" || type == "ControlType.ListItem";
        }
        internal static int UiaTextCount(Report report)
        {
            return report.Nodes.Count(n => n.Depth > 0 && !n.Skipped &&
                (!String.IsNullOrWhiteSpace(n.Name) || !String.IsNullOrWhiteSpace(n.Text) || !String.IsNullOrWhiteSpace(n.Value)));
        }
        internal static int MsaaTextCount(Report report)
        {
            return report.MsaaNodes.Count(n => n.Depth > 0 && !n.Skipped &&
                (!String.IsNullOrWhiteSpace(n.Name) || !String.IsNullOrWhiteSpace(n.Value)));
        }
        internal static string Finding(Report report)
        {
            if (UiaTextCount(report) + MsaaTextCount(report) > 0)
                return "有取得子元件文字，尚須人工核對是否為留言、作者和時間。";
            if (report.Status == "not_started" || report.Status == "failed" || report.Status == "timeout" || report.Status == "minimized")
                return "讀取未完成，目前無法判定是否提供聊天文字。";
            return "尚未讀到子元件文字；介面掃描完成不等於取得聊天內容。";
        }
        internal static string Clip(string text, int limit, NodeInfo node)
        {
            if (text == null || text.Length <= limit) return text;
            node.TextTruncated = true;
            // Keep Unicode surrogate pairs intact.
            if (limit > 0 && Char.IsHighSurrogate(text[limit - 1])) limit--;
            return text.Substring(0, limit);
        }
        internal static void Save(string path, object value) { File.WriteAllText(path, Serializer().Serialize(value), Utf8); }
        internal static string Quote(string text)
        {
            // Windows command-line quoting, including backslashes before quotes and the closing quote.
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in text)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); }
                else { result.Append('\\', slashes); result.Append(c); }
                slashes = 0;
            }
            result.Append('\\', slashes * 2);
            return result.Append('"').ToString();
        }
        internal static string Render(Report report)
        {
            var text = new StringBuilder();
            text.AppendLine("LINE 唯讀文字診斷 v2.1");
            text.AppendLine("時間（UTC）：" + report.CapturedAtUtc);
            text.AppendLine("目標：" + (report.Target == null ? "未指定" : report.Target.Title));
            text.AppendLine("狀態：" + report.Status);
            text.AppendLine("文字結果：" + Finding(report));
            text.AppendLine("已讀元件：" + report.Nodes.Count);
            text.AppendLine("UIA 有文字的子元件：" + UiaTextCount(report));
            text.AppendLine("MSAA 狀態：" + report.MsaaStatus + "；元件：" + report.MsaaNodes.Count + "；有文字的子元件：" + MsaaTextCount(report));
            int unavailableDescriptions = report.MsaaNodes.Count(n => n.UnavailableFields.Any(f => f.StartsWith("Description:", StringComparison.Ordinal)));
            if (unavailableDescriptions > 0) text.AppendLine("MSAA 說明：" + unavailableDescriptions + " 個元件不提供描述欄位，屬於介面能力限制，不列為讀取失敗。");
            if (!String.IsNullOrEmpty(report.MsaaError)) text.AppendLine("MSAA 說明：" + report.MsaaError);
            text.AppendLine("完整留言核對：尚未驗證（本工具不判定是否完整收單）");
            if (!String.IsNullOrEmpty(report.Error)) text.AppendLine("錯誤：" + report.Error);
            foreach (string note in report.Notes.Distinct()) text.AppendLine("說明：" + note);
            text.AppendLine();
            text.AppendLine("以下為原始介面文字；按鈕、標籤或重複元件不等同訊息。");
            foreach (NodeInfo node in report.Nodes)
            {
                text.AppendLine();
                text.AppendLine(String.Format(CultureInfo.InvariantCulture, "[{0}] parent={1} depth={2} {3} offscreen={4}", node.Index, node.Parent, node.Depth, node.ControlType, node.Offscreen));
                if (node.Skipped) { text.AppendLine("（輸入或密碼元件：略過）"); continue; }
                if (!String.IsNullOrEmpty(node.Name)) text.AppendLine("Name: " + node.Name);
                if (!String.IsNullOrEmpty(node.Text)) text.AppendLine("TextPattern: " + node.Text);
                if (!String.IsNullOrEmpty(node.Value)) text.AppendLine("Value（僅讀取）：" + node.Value);
                text.AppendLine("Class: " + node.ClassName + "; Framework: " + node.FrameworkId);
                text.AppendLine("Patterns: " + (node.SupportedPatterns.Count == 0 ? "（未提供或未取得）" : String.Join(", ", node.SupportedPatterns)));
                if (!String.IsNullOrEmpty(node.TextReadPolicy)) text.AppendLine("Text policy: " + node.TextReadPolicy);
                if (!String.IsNullOrEmpty(node.ValueReadPolicy)) text.AppendLine("Value policy: " + node.ValueReadPolicy + "; provider IsReadOnly=" + node.ValuePatternIsReadOnly);
                if (!String.IsNullOrEmpty(node.HelpText)) text.AppendLine("HelpText: " + node.HelpText);
                if (!String.IsNullOrEmpty(node.ItemStatus)) text.AppendLine("ItemStatus: " + node.ItemStatus);
                if (node.TextTruncated) text.AppendLine("（文字已截短）");
                foreach (string error in node.Errors) text.AppendLine("讀取異常：" + error);
            }
            text.AppendLine();
            text.AppendLine("MSAA 原始資料（與 UIA 分開保留，不合併、不去重）");
            foreach (MsaaNode node in report.MsaaNodes)
            {
                text.AppendLine();
                text.AppendLine(String.Format(CultureInfo.InvariantCulture, "[MSAA {0}] parent={1} depth={2} role={3} state={4}", node.Index, node.Parent, node.Depth, node.Role, node.State));
                if (node.Skipped) { text.AppendLine("（輸入／密碼元件或無法確認狀態：略過）"); continue; }
                if (!String.IsNullOrEmpty(node.Name)) text.AppendLine("Name: " + node.Name);
                if (!String.IsNullOrEmpty(node.Value)) text.AppendLine("Value: " + node.Value);
                if (!String.IsNullOrEmpty(node.Description)) text.AppendLine("Description: " + node.Description);
                if (node.TextTruncated) text.AppendLine("（文字已截短）");
                foreach (string error in node.Errors) text.AppendLine("讀取異常：" + error);
            }
            return text.ToString();
        }

        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                if (args.Length == 2 && args[0] == "--self-test") { SelfTest.Run(args[1]); return 0; }
                if (args.Length == 2 && args[0] == "--msaa-fixture-test") { MsaaReader.TestFixture(args[1]); return 0; }
                if (args.Length == 2 && args[0] == "--preview")
                {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    using (var form = new MainForm()) form.SavePreview(args[1]);
                    return 0;
                }
                if (args.Length == 2 && args[0] == "--list-worker") { Save(args[1], Native.ListLineWindows()); return 0; }
                if (args.Length == 3 && args[0] == "--read-worker")
                {
                    WindowInfo target = Serializer().Deserialize<WindowInfo>(File.ReadAllText(args[1], Encoding.UTF8));
                    Save(args[2], Reader.Read(target));
                    return 0;
                }
                if (args.Length == 3 && args[0] == "--msaa-worker")
                {
                    var report = Serializer().Deserialize<Report>(File.ReadAllText(args[1], Encoding.UTF8));
                    MsaaReader.Read(report);
                    Save(args[2], report);
                    return 0;
                }
                if (args.Length != 0) return 2;
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new MainForm());
                return 0;
            }
            catch (Exception ex)
            {
                // Worker failures do not create a modal or interact with LINE.
                if (args.Length == 0) MessageBox.Show(ex.Message, "診斷工具無法啟動");
                else if (args.Length == 2 && (args[0] == "--self-test" || args[0] == "--msaa-fixture-test"))
                {
                    try { Save(args[1], new { status = "failed", error = ex.ToString(), liveLineRead = false }); } catch { }
                }
                return 1;
            }
        }
    }

    internal sealed class MainForm : Form
    {
        private readonly ComboBox windows = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
        private readonly Button refresh = new Button { Text = "重新整理 LINE 視窗", AutoSize = true };
        private readonly Button read = new Button { Text = "讀取選定視窗", AutoSize = true, Enabled = false };
        private readonly Button folder = new Button { Text = "開啟報告資料夾", AutoSize = true };
        private readonly Label status = new Label { Text = "先按「重新整理 LINE 視窗」，再選擇要讀取的社群。", AutoSize = true, Dock = DockStyle.Fill };
        private readonly TextBox output = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, WordWrap = false, Dock = DockStyle.Fill };
        private bool busy;
        private Process worker;
        private readonly string dataDirectory = Path.Combine(Program.Root, "data");

        internal MainForm()
        {
            Text = "LINE 唯讀文字診斷 v2.1 — UIA + MSAA";
            Size = new Size(980, 740);
            MinimumSize = new Size(740, 540);
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft JhengHei UI", 10F);
            var panel = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 1, RowCount = 6 };
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.Controls.Add(new Label { Text = "請自行在 LINE 打開社群／討論串，再選擇下方視窗。", AutoSize = true }, 0, 0);
            panel.Controls.Add(new Label { Text = "只讀一次目前介面提供的文字；不點擊、不捲動、不截圖、不連網、不寫入訂單。", AutoSize = true, Padding = new Padding(0, 5, 0, 10) }, 0, 1);
            panel.Controls.Add(windows, 0, 2);
            var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, Padding = new Padding(0, 8, 0, 8) };
            buttons.Controls.AddRange(new Control[] { refresh, read, folder });
            panel.Controls.Add(buttons, 0, 3);
            panel.Controls.Add(output, 0, 4);
            status.Padding = new Padding(0, 10, 0, 0);
            panel.Controls.Add(status, 0, 5);
            Controls.Add(panel);
            refresh.Click += async delegate { await RefreshWindows(); };
            read.Click += async delegate { await ReadWindow(); };
            windows.SelectedIndexChanged += delegate { read.Enabled = !busy && windows.SelectedItem != null; };
            folder.Click += delegate
            {
                try { Directory.CreateDirectory(dataDirectory); Process.Start(new ProcessStartInfo(dataDirectory) { UseShellExecute = true }); }
                catch (Exception ex) { status.Text = "無法開啟資料夾：" + ex.Message; }
            };
            FormClosing += delegate { if (worker != null) { try { if (!worker.HasExited) worker.Kill(); } catch { } } };
        }
        internal void SavePreview(string path)
        {
            // Offline layout fixture only. Does not enumerate windows, use UIA, or start a worker.
            windows.Items.Add(new WindowInfo { Title = "版面測試社群（模擬資料）", ProcessId = 1234 });
            windows.SelectedIndex = 0;
            var sample = new Report { Status = "snapshot_ready", Target = (WindowInfo)windows.SelectedItem };
            sample.Notes.Add("這是版面預覽用的模擬文字，未讀取 LINE。");
            sample.Nodes.Add(new NodeInfo { Index = 0, Parent = -1, ControlType = "ControlType.Window", Name = "版面測試社群" });
            sample.Nodes.Add(new NodeInfo { Index = 1, Parent = 0, Depth = 1, ControlType = "ControlType.Text", Name = "測試客人　11:05\r\n生豆包 50/包(5入)*6\r\n葡萄＋1" });
            output.Text = Program.Render(sample);
            status.Text = "模擬畫面：這裡會顯示報告路徑及讀取狀態。";
            CreatePreviewHandles(this);
            PerformLayout();
            using (var bitmap = new Bitmap(Width, Height))
            {
                DrawToBitmap(bitmap, new Rectangle(0, 0, Width, Height));
                bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png);
            }
        }
        private static void CreatePreviewHandles(Control control)
        {
            IntPtr handle = control.Handle;
            foreach (Control child in control.Controls) CreatePreviewHandles(child);
            control.PerformLayout();
        }
        private void Busy(bool value)
        {
            busy = value;
            refresh.Enabled = !value;
            windows.Enabled = !value;
            read.Enabled = !value && windows.SelectedItem != null;
        }
        private async Task ExecuteWorker(string arguments, int timeoutSeconds)
        {
            using (var process = new Process())
            {
                process.StartInfo = new ProcessStartInfo(Application.ExecutablePath, arguments)
                { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, WorkingDirectory = Program.Root };
                worker = process;
                process.Start();
                bool finished = await Task.Run(() => process.WaitForExit(timeoutSeconds * 1000));
                if (!finished)
                {
                    try { process.Kill(); process.WaitForExit(2000); } catch { }
                    throw new TimeoutException("讀取程序逾時並已嘗試終止。沒有成功報告；不代表 LINE 沒有訊息。");
                }
                if (process.ExitCode != 0) throw new InvalidOperationException("讀取程序未成功結束（" + process.ExitCode + "）。請確認 LINE 視窗仍存在，並以一般權限執行。");
                worker = null;
            }
        }
        private async Task RefreshWindows()
        {
            Busy(true);
            string listing = null;
            try
            {
                Directory.CreateDirectory(dataDirectory);
                listing = Path.Combine(dataDirectory, "windows-" + Guid.NewGuid().ToString("N") + ".json");
                status.Text = "正在列出 LINE 視窗標題；尚未讀取聊天內容…";
                await ExecuteWorker("--list-worker " + Program.Quote(listing), 12);
                if (IsDisposed) return;
                var found = Program.Serializer().Deserialize<List<WindowInfo>>(File.ReadAllText(listing, Encoding.UTF8));
                windows.Items.Clear();
                foreach (WindowInfo item in found) windows.Items.Add(item);
                windows.SelectedIndex = -1;
                status.Text = found.Count == 0 ? "找不到可選的 LINE 視窗。請自行登入 LINE 並打開社群。" : "找到 " + found.Count + " 個 LINE 視窗。請依完整標題選擇，避免選到登入或主視窗。";
            }
            catch (Exception ex) { if (!IsDisposed) status.Text = ex.Message; }
            finally
            {
                if (listing != null && File.Exists(listing)) { try { File.Delete(listing); } catch { } }
                worker = null;
                if (!IsDisposed) Busy(false);
            }
        }
        private async Task ReadWindow()
        {
            var target = windows.SelectedItem as WindowInfo;
            if (target == null) return;
            Busy(true);
            string stem = Path.Combine(dataDirectory, "read-v2.1-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 6));
            string request = stem + ".request.json";
            string result = stem + ".json";
            try
            {
                Directory.CreateDirectory(dataDirectory);
                Program.Save(request, target);
                status.Text = "第 1/2 階段：UIA 唯讀擷取，最多 40 秒。請保持 LINE 社群／串文不變。";
                output.Text = "讀取中…";
                Report report;
                try
                {
                    await ExecuteWorker("--read-worker " + Program.Quote(request) + " " + Program.Quote(result), 40);
                    if (IsDisposed) return;
                    report = Program.Serializer().Deserialize<Report>(File.ReadAllText(result, Encoding.UTF8));
                }
                catch (Exception ex)
                {
                    report = new Report { Target = target, Status = ex is TimeoutException ? "timeout" : "failed", Error = ex.Message };
                    Program.Save(result, report);
                }
                if (IsDisposed) return;
                // Preserve the first phase even if the independent MSAA worker hangs or fails.
                // MSAA checks target identity independently, including after a UIA failure.
                if (report.Status != "minimized")
                {
                    status.Text = "第 2/2 階段：MSAA 唯讀擷取，最多 25 秒。UIA 結果已保存。";
                    string msaaResult = stem + ".msaa.json";
                    try
                    {
                        await ExecuteWorker("--msaa-worker " + Program.Quote(result) + " " + Program.Quote(msaaResult), 25);
                        if (IsDisposed) return;
                        report = Program.Serializer().Deserialize<Report>(File.ReadAllText(msaaResult, Encoding.UTF8));
                    }
                    catch (Exception ex)
                    {
                        report.MsaaStatus = ex is TimeoutException ? "timeout" : "failed";
                        report.MsaaError = ex.Message;
                    }
                    finally { if (File.Exists(msaaResult)) { try { File.Delete(msaaResult); } catch { } } }
                    Program.Save(result, report);
                }
                string rendered = Program.Render(report);
                File.WriteAllText(stem + ".txt", rendered, Program.Utf8);
                output.Text = rendered;
                status.Text = Program.Finding(report) + " 報告已保存。";
            }
            catch (Exception ex)
            {
                if (!IsDisposed)
                {
                    var failed = new Report { Target = target, Status = ex is TimeoutException ? "timeout" : "failed", Error = ex.Message };
                    output.Text = Program.Render(failed);
                    try { Program.Save(result, failed); File.WriteAllText(stem + ".txt", output.Text, Program.Utf8); } catch { }
                    status.Text = "未成功完成讀取：" + ex.Message;
                }
            }
            finally
            {
                if (File.Exists(request)) { try { File.Delete(request); } catch { } }
                worker = null;
                if (!IsDisposed) Busy(false);
            }
        }
    }

    internal static class SelfTest
    {
        internal static void Run(string path)
        {
            var passed = new List<string>();
            Action<bool, string> check = delegate(bool condition, string name)
            {
                if (!condition) throw new InvalidOperationException("Self-test failed: " + name);
                passed.Add(name);
            };
            check(Program.SkipControl("ControlType.Edit", false), "editable_controls_skipped");
            check(Program.SkipControl("ControlType.Text", true), "password_controls_skipped");
            check(!Program.ReadTextPattern("ControlType.Window") && !Program.ReadTextPattern("ControlType.Edit"), "window_and_input_text_not_aggregated");
            check(Program.ReadTextPattern("ControlType.Group") && Program.ReadTextPattern("ControlType.ListItem"), "line_group_and_listitem_patterns_examined");
            check(Program.SkipControl("ControlType.Group", false, "MessageInputPanel"), "line_input_panel_subtree_skipped");
            check(Program.IsExplicitlyReadOnly(true) && !Program.IsExplicitlyReadOnly(false) && !Program.IsExplicitlyReadOnly(null) && !Program.IsExplicitlyReadOnly("true"), "text_range_requires_explicit_read_only_flag");
            check(MsaaReader.Skip(42, 0) && MsaaReader.Skip(41, 0x20000000) && !MsaaReader.Skip(41, 0), "msaa_edit_and_protected_roles_skipped");
            check(Program.CanReadValue("ControlType.Group", "LcText", false) && Program.CanReadValue("ControlType.ListItem", "", false), "qt_labels_and_listitems_allow_getter_without_readonly_flag");
            check(!Program.CanReadValue("ControlType.Edit", "", true) && !Program.CanReadValue("ControlType.Group", "MessageInputPanel", true) && !Program.CanReadValue("ControlType.Group", "LcWidget", false), "value_getter_does_not_expand_into_input_or_unknown_editable_containers");
            var optional = new MsaaNode();
            MsaaReader.RecordPropertyError(optional, "Description", unchecked((int)0x80020003));
            check(optional.Errors.Count == 0 && optional.UnavailableFields.Count == 1, "unsupported_description_is_capability_not_traversal_error");
            MsaaReader.RecordPropertyError(optional, "Description", unchecked((int)0x80070005));
            check(optional.Errors.Count == 1, "real_access_error_is_preserved");
            var first = new WindowInfo { Handle = 10, ProcessId = 20, ProcessStartedUtc = "one", Title = "測試社群" };
            var changed = new WindowInfo { Handle = 10, ProcessId = 20, ProcessStartedUtc = "two", Title = "測試社群" };
            check(!Program.SameTarget(first, changed), "reused_process_identity_rejected");
            changed.ProcessStartedUtc = "one"; changed.Title = "另一個社群";
            check(!Program.SameTarget(first, changed), "changed_title_rejected");
            changed.Title = first.Title;
            check(Program.SameTarget(first, changed), "exact_target_match");
            var node = new NodeInfo();
            check(Program.Clip("甲😀乙", 2, node) == "甲" && node.TextTruncated, "unicode_truncation_preserves_surrogate_pairs");
            var report = new Report { Target = first, Status = "partial" };
            report.Nodes.Add(new NodeInfo { Index = 0, Name = "生豆包 50/包(5入)*6\r\n＋1", ControlType = "ControlType.Text" });
            report.Nodes.Add(new NodeInfo { Index = 1, Name = "生豆包 50/包(5入)*6\r\n＋1", ControlType = "ControlType.Text" });
            var restored = Program.Serializer().Deserialize<Report>(Program.Serializer().Serialize(report));
            check(restored.Nodes.Count == 2 && restored.Nodes[0].Name == report.Nodes[0].Name, "raw_unicode_newlines_and_duplicate_nodes_preserved");
            check(!restored.MessageCompletenessVerified && Program.Render(restored).Contains("尚未驗證"), "no_false_message_completeness_claim");
            var empty = new Report { Status = "snapshot_ready" };
            empty.Nodes.Add(new NodeInfo { Depth = 0, Name = "只有視窗標題" });
            check(Program.UiaTextCount(empty) == 0 && Program.Finding(empty).Contains("尚未讀到"), "window_title_is_not_message_extraction");
            empty.MsaaNodes.Add(new MsaaNode { Index = 0, Depth = 0, Name = "MSAA 根元件" });
            empty.MsaaNodes.Add(new MsaaNode { Index = 1, Depth = 1, Name = "葡萄＋1" });
            check(Program.MsaaTextCount(empty) == 1 && Program.Finding(empty).Contains("尚須人工核對"), "msaa_candidates_not_claimed_as_verified_messages");
            check(Program.Quote("a b") == "\"a b\"", "argument_spaces_quoted");
            check(Program.Quote("a\"b") == "\"a\\\"b\"", "argument_quote_escaped");
            check(Program.Quote("C:\\folder\\") == "\"C:\\folder\\\\\"", "argument_trailing_slash_escaped");
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            Program.Save(path, new { status = "passed", checks = passed, liveLineRead = false, note = "Offline tests only. No window enumeration or UI Automation calls." });
        }
    }
}
