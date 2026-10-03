using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using Accessibility;

namespace LineReaderDiagnostic
{
    public sealed class MsaaNode
    {
        public int Index;
        public int Parent;
        public int Depth;
        public int ChildId;
        public int Role;
        public int State;
        public string Name;
        public string Value;
        public string Description;
        public bool Skipped;
        public bool TextTruncated;
        public List<string> Errors = new List<string>();
        public List<string> UnavailableFields = new List<string>();
    }

    internal static class MsaaReader
    {
        [DllImport("oleacc.dll", ExactSpelling = true, PreserveSig = true)]
        private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint objectId, ref Guid iid,
            [MarshalAs(UnmanagedType.Interface)] out IAccessible accessible);
        [DllImport("oleacc.dll", ExactSpelling = true, PreserveSig = true)]
        private static extern int AccessibleChildren([MarshalAs(UnmanagedType.Interface)] IAccessible container,
            int start, int count, [Out, MarshalAs(UnmanagedType.LPArray, SizeParamIndex = 2)] object[] children, out int obtained);

        private sealed class Work { internal IAccessible Object; internal int ChildId; internal int Parent; internal int Depth; }
        internal static bool Skip(int role, int state) { return role == 42 || (state & 0x20000000) != 0; }
        internal static void RecordPropertyError(MsaaNode node, string field, int errorCode)
        {
            string detail = field + ": HRESULT 0x" + errorCode.ToString("X8", CultureInfo.InvariantCulture);
            if (errorCode == unchecked((int)0x80020003) || errorCode == unchecked((int)0x80004001))
                node.UnavailableFields.Add(detail);
            else node.Errors.Add(detail);
        }
        internal static void TestFixture(string outputPath)
        {
            // Exercise COM signatures against this process's own hidden synthetic controls only.
            using (var fixture = new System.Windows.Forms.Form())
            using (var label = new System.Windows.Forms.Label())
            using (var input = new System.Windows.Forms.TextBox())
            {
                fixture.Text = "MSAA fixture";
                label.Text = "測試商品＋1";
                label.AccessibleName = "測試商品＋1";
                input.AccessibleName = "測試輸入欄";
                input.Text = "不應當成留言";
                fixture.Controls.Add(label);
                fixture.Controls.Add(input);
                IntPtr handle = fixture.Handle;
                IntPtr labelHandle = label.Handle;
                IntPtr inputHandle = input.Handle;
                Guid iid = new Guid("618736E0-3C3D-11CF-810C-00AA00389B71");
                IAccessible accessible;
                int hr = AccessibleObjectFromWindow(handle, unchecked((uint)-4), ref iid, out accessible);
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                if (accessible == null) throw new InvalidOperationException("Fixture root missing");
                var children = new object[accessible.accChildCount];
                try
                {
                    int obtained;
                    hr = AccessibleChildren(accessible, 0, children.Length, children, out obtained);
                    if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                    bool foundLabel = false;
                    bool skippedEdit = false;
                    var observed = new List<string>();
                    for (int i = 0; i < obtained; i++)
                    {
                        IAccessible child = children[i] as IAccessible;
                        int id = child == null && children[i] is int ? (int)children[i] : 0;
                        IAccessible source = child ?? accessible;
                        int role = (int)source.get_accRole(id);
                        int state = (int)source.get_accState(id);
                        observed.Add("role=" + role + ", state=" + state + ", name=" + source.get_accName(id));
                        if (Skip(role, state)) { skippedEdit = true; continue; }
                        if (source.get_accName(id) == "測試商品＋1") foundLabel = true;
                    }
                    // WinForms returns child window wrappers (ROLE_SYSTEM_WINDOW) at this level.
                    // Probe the fixture input's client object to verify the actual editable role.
                    IAccessible inputAccessible;
                    int inputHr = AccessibleObjectFromWindow(inputHandle, unchecked((uint)-4), ref iid, out inputAccessible);
                    if (inputHr < 0) Marshal.ThrowExceptionForHR(inputHr);
                    try { skippedEdit = Skip((int)inputAccessible.get_accRole(0), (int)inputAccessible.get_accState(0)); }
                    finally { if (inputAccessible != null && Marshal.IsComObject(inputAccessible)) Marshal.ReleaseComObject(inputAccessible); }
                    if (!foundLabel || !skippedEdit) throw new InvalidOperationException("MSAA fixture extraction did not match expected label/input roles. Count=" + children.Length + ", obtained=" + obtained + "; " + String.Join("; ", observed));
                    Program.Save(outputPath, new { status = "passed", extractedLabel = "測試商品＋1", skippedEdit = skippedEdit,
                        children = obtained, liveLineRead = false, note = "Own-process hidden synthetic controls only; no LINE access, screenshots, clicks, or network." });
                }
                finally
                {
                    foreach (object child in children) if (child != null && Marshal.IsComObject(child)) Marshal.ReleaseComObject(child);
                    if (Marshal.IsComObject(accessible)) Marshal.ReleaseComObject(accessible);
                }
            }
        }
        private static string Text(Func<string> read, MsaaNode node, string field, int limit)
        {
            try
            {
                var clip = new NodeInfo();
                string result = Program.Clip(read(), limit, clip);
                node.TextTruncated |= clip.TextTruncated;
                return result;
            }
            catch (COMException ex)
            {
                // Unsupported optional properties are capabilities, not failed traversal.
                RecordPropertyError(node, field, ex.ErrorCode);
                return null;
            }
            catch (Exception ex) { node.Errors.Add(field + ": " + ex.GetType().Name); return null; }
        }
        internal static void Read(Report report)
        {
            report.MsaaStatus = "reading";
            report.Notes.Add("MSAA 使用同一個選定視窗的 client 無障礙物件；不呼叫任何選取、輸入、捲動或預設動作。");
            report.Notes.Add("MSAA 與 UIA 結果分開保留；child ID 僅為本次介面階層索引，並非 LINE 訊息 ID。");
            var returnedComObjects = new List<object>();
            try
            {
                Native.Validate(report.Target);
                if (Native.IsIconic(new IntPtr(report.Target.Handle)))
                    throw new InvalidOperationException("LINE 已最小化；未讀取 MSAA，請自行還原視窗後重試。");
                Guid iid = new Guid("618736E0-3C3D-11CF-810C-00AA00389B71");
                IAccessible root;
                int hr = AccessibleObjectFromWindow(new IntPtr(report.Target.Handle), unchecked((uint)-4), ref iid, out root);
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                if (root == null) throw new InvalidOperationException("指定視窗未提供 MSAA client 物件。");
                returnedComObjects.Add(root);
                var queue = new Queue<Work>();
                queue.Enqueue(new Work { Object = root, ChildId = 0, Parent = -1, Depth = 0 });
                var clock = Stopwatch.StartNew();
                bool limited = false;
                bool errors = false;
                while (queue.Count > 0)
                {
                    if (clock.Elapsed.TotalSeconds > 18 || report.MsaaNodes.Count >= report.MaxNodes) { limited = true; break; }
                    Native.Validate(report.Target);
                    Work item = queue.Dequeue();
                    var node = new MsaaNode { Index = report.MsaaNodes.Count, Parent = item.Parent, Depth = item.Depth, ChildId = item.ChildId };
                    report.MsaaNodes.Add(node);
                    try
                    {
                        object role = item.Object.get_accRole(item.ChildId);
                        object state = item.Object.get_accState(item.ChildId);
                        if (!(role is int) || !(state is int))
                        {
                            node.Skipped = true;
                            node.Errors.Add("無法確認 role/state；不讀取此元件或子樹。");
                            errors = true;
                            continue;
                        }
                        node.Role = (int)role;
                        node.State = (int)state;
                        node.Skipped = Skip(node.Role, node.State);
                        if (node.Skipped) continue;
                        node.Name = Text(() => item.Object.get_accName(item.ChildId), node, "Name", report.MaxTextChars);
                        node.Description = Text(() => item.Object.get_accDescription(item.ChildId), node, "Description", report.MaxTextChars);
                        // Value is restricted to explicitly read-only objects, static text, and list items.
                        if ((node.State & 0x40) != 0 || node.Role == 41 || node.Role == 34)
                            node.Value = Text(() => item.Object.get_accValue(item.ChildId), node, "Value", report.MaxTextChars);
                        if (node.Errors.Count > 0) errors = true;
                        if (node.TextTruncated) limited = true;
                        // Simple child IDs are leaf elements; object children expose their own IAccessible.
                        if (item.ChildId != 0) continue;
                        int childCount = item.Object.accChildCount;
                        if (childCount <= 0) continue;
                        if (item.Depth >= report.MaxDepth) { limited = true; continue; }
                        int capacity = report.MaxNodes - report.MsaaNodes.Count - queue.Count;
                        int count = Math.Min(childCount, Math.Max(0, capacity));
                        if (count < childCount) limited = true;
                        if (count == 0) continue;
                        var children = new object[count];
                        int obtained;
                        int result = AccessibleChildren(item.Object, 0, count, children, out obtained);
                        // Keep references for deterministic release after all queued traversal work completes.
                        foreach (object child in children)
                            if (child != null && Marshal.IsComObject(child)) returnedComObjects.Add(child);
                        if (result < 0) Marshal.ThrowExceptionForHR(result);
                        if (obtained != count) { errors = true; node.Errors.Add("子元件數於讀取期間改變，未確認完整。"); }
                        for (int i = 0; i < Math.Min(obtained, children.Length); i++)
                        {
                            var childObject = children[i] as IAccessible;
                            if (childObject != null)
                                queue.Enqueue(new Work { Object = childObject, ChildId = 0, Parent = node.Index, Depth = item.Depth + 1 });
                            else if (children[i] is int && (int)children[i] > 0)
                                queue.Enqueue(new Work { Object = item.Object, ChildId = (int)children[i], Parent = node.Index, Depth = item.Depth + 1 });
                            else { errors = true; node.Errors.Add("未辨識的 MSAA 子元件型別，已略過。"); }
                        }
                    }
                    catch (Exception ex)
                    {
                        errors = true;
                        node.Errors.Add(ex.GetType().Name + ": " + ex.Message);
                    }
                }
                Native.Validate(report.Target);
                report.MsaaStatus = limited || errors ? "partial" : "snapshot_ready";
                if (limited) report.Notes.Add("MSAA 有部分資料達到讀取上限；不可視為完整留言。");
            }
            catch (Exception ex)
            {
                report.MsaaStatus = "failed";
                report.MsaaError = ex.GetType().Name + ": " + ex.Message;
            }
            finally
            {
                foreach (object item in returnedComObjects)
                {
                    try { if (Marshal.IsComObject(item)) Marshal.ReleaseComObject(item); }
                    catch (InvalidComObjectException) { }
                }
            }
        }
    }
}
