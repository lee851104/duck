using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace LineExportMonitor
{
    public sealed class ChatEntry
    {
        public string Date { get;set; }
        public string Time { get;set; }
        // LINE's space-delimited export cannot reliably separate names containing spaces.
        public string Raw { get;set; }
        public string Key { get { return Date+"\n"+Raw; } }
    }
    public sealed class DeltaResult
    {
        public string Status { get;set; }
        public string Reason { get;set; }
        public int Overlap { get;set; }
        public List<ChatEntry> Added { get;set; }
    }
    public sealed class Baseline
    {
        public int Version=1;
        public string TargetTitle;
        public string UpdatedUtc;
        public string Digest;
        public List<ChatEntry> Entries;
    }
    internal static class ExportDelta
    {
        internal static readonly Encoding Utf8=new UTF8Encoding(false,true);
        internal static readonly JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=100000000 };
        private static readonly Regex DateLine=new Regex(@"^(\d{4}\.\d{2}\.\d{2})\s+星期[一二三四五六日天]\s*$");
        private static readonly Regex MessageLine=new Regex(@"^([0-2]\d:[0-5]\d) (.+)$");
        internal static string Read(string path)
        {
            var bytes=File.ReadAllBytes(path);
            if(bytes.Length>30000000) throw new Exception("聊天檔超過 30 MB，已暫停，未更換基準。");
            if(bytes.Length>=2 && bytes[0]==255 && bytes[1]==254) return new UnicodeEncoding(false,true,true).GetString(bytes,2,bytes.Length-2);
            if(bytes.Length>=2 && bytes[0]==254 && bytes[1]==255) return new UnicodeEncoding(true,true,true).GetString(bytes,2,bytes.Length-2);
            int skip=bytes.Length>=3 && bytes[0]==239 && bytes[1]==187 && bytes[2]==191 ? 3:0;
            return Utf8.GetString(bytes,skip,bytes.Length-skip);
        }
        internal static List<ChatEntry> Parse(string text)
        {
            var result=new List<ChatEntry>(); string date=null; ChatEntry current=null;
            foreach(string line in text.Replace("\r\n","\n").Replace("\r","\n").Split('\n')) {
                var dm=DateLine.Match(line);
                if(dm.Success) {
                    DateTime d; if(!DateTime.TryParseExact(dm.Groups[1].Value,"yyyy.MM.dd",CultureInfo.InvariantCulture,DateTimeStyles.None,out d)) throw new Exception("聊天檔日期格式錯誤。");
                    date=d.ToString("yyyy-MM-dd"); current=null; continue;
                }
                var mm=MessageLine.Match(line);
                if(date!=null && mm.Success) {
                    if(Int32.Parse(mm.Groups[1].Value.Substring(0,2))>23) throw new Exception("聊天檔時間格式錯誤。");
                    current=new ChatEntry { Date=date,Time=mm.Groups[1].Value,Raw=line }; result.Add(current); continue;
                }
                if(current!=null) current.Raw+="\n"+line;
                else if(!String.IsNullOrWhiteSpace(line) && !(date==null && (line.StartsWith("[LINE]") || line.StartsWith("儲存日期") || line.StartsWith("儲存時間"))))
                    throw new Exception("聊天檔有無法辨識的區段，已保留檔案；不猜測訊息邊界。");
            }
            foreach(var entry in result) entry.Raw=entry.Raw.TrimEnd('\n');
            if(result.Count==0) throw new Exception("聊天檔沒有可辨識的日期與時間記錄。");
            return result;
        }
        internal static string Digest(IEnumerable<ChatEntry> entries) { return Hash(Json.Serialize(entries)); }
        internal static string Hash(string s) { using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Utf8.GetBytes(s))).Replace("-","").ToLowerInvariant(); }
        internal static DeltaResult Compare(List<ChatEntry> oldEntries,List<ChatEntry> fresh)
        {
            int prefix=0;
            while(prefix<oldEntries.Count && prefix<fresh.Count && oldEntries[prefix].Key==fresh[prefix].Key) prefix++;
            if(prefix==oldEntries.Count) return new DeltaResult { Status="matched",Overlap=prefix,Added=fresh.Skip(prefix).ToList() };
            if(prefix==fresh.Count) return new DeltaResult { Status="review_required",Reason="新檔比舊檔短，且沒有涵蓋原本最後一筆；可能尚未載入完整。",Added=new List<ChatEntry>() };
            // KMP: largest ordered suffix(old) == prefix(new), preserving duplicate occurrences.
            var pattern=fresh.Select(e=>e.Key).ToArray(); var pi=new int[pattern.Length];
            for(int i=1,j=0;i<pattern.Length;i++) { while(j>0 && pattern[i]!=pattern[j]) j=pi[j-1]; if(pattern[i]==pattern[j]) j++; pi[i]=j; }
            int overlap=0;
            foreach(var entry in oldEntries) {
                while(overlap>0 && (overlap==pattern.Length || pattern[overlap]!=entry.Key)) overlap=pi[overlap-1];
                if(overlap<pattern.Length && pattern[overlap]==entry.Key) overlap++;
            }
            if(overlap<3) return new DeltaResult { Status="review_required",Reason="找不到至少 3 筆連續重疊記錄；可能缺段、收回或修改了訊息。",Added=new List<ChatEntry>() };
            int occurrences=0;
            for(int i=0;i<=oldEntries.Count-overlap;i++) {
                if(oldEntries[i].Key!=fresh[0].Key) continue;
                int j=1; while(j<overlap && oldEntries[i+j].Key==fresh[j].Key) j++;
                if(j==overlap) occurrences++;
            }
            if(occurrences!=1) return new DeltaResult { Status="review_required",Reason="重疊區段出現多次，無法唯一對齊；未刪除任何輸入。",Added=new List<ChatEntry>() };
            return new DeltaResult { Status="matched",Overlap=overlap,Added=fresh.Skip(overlap).ToList() };
        }
        internal static string Render(IEnumerable<ChatEntry> entries)
        {
            var s=new StringBuilder(); string date=null;
            foreach(var entry in entries) { if(entry.Date!=date) { date=entry.Date; s.AppendLine(date); } s.AppendLine(entry.Raw.Replace("\n","\r\n")); }
            return s.ToString();
        }
        internal static void AtomicWrite(string path,string content)
        {
            string temp=path+"."+Guid.NewGuid().ToString("N")+".tmp";
            using(var fs=new FileStream(temp,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                byte[] bytes=Utf8.GetBytes(content); fs.Write(bytes,0,bytes.Length); fs.Flush(true);
            }
            if(File.Exists(path)) File.Replace(temp,path,null); else File.Move(temp,path);
        }
    }
    internal sealed class DeltaStore
    {
        internal readonly string Root;
        internal Baseline State;
        internal DeltaStore(string root) {
            Root=Path.GetFullPath(root); Directory.CreateDirectory(Root);
            string file=Path.Combine(Root,"state.json");
            if(File.Exists(file)) {
                State=ExportDelta.Json.Deserialize<Baseline>(File.ReadAllText(file,ExportDelta.Utf8));
                if(State==null || State.Version!=1 || State.Entries==null || State.Digest!=ExportDelta.Digest(State.Entries)) throw new Exception("比對基準損壞，已停止；請保留資料夾以便檢查。");
            }
        }
        internal void Initialize(string file,string target) {
            if(State!=null) throw new Exception("已有基準，不能自動覆蓋。");
            var entries=ExportDelta.Parse(ExportDelta.Read(file)); SaveState(entries,target);
        }
        private void SaveState(List<ChatEntry> entries,string title) {
            var next=new Baseline { Entries=entries,TargetTitle=title,UpdatedUtc=DateTime.UtcNow.ToString("o"),Digest=ExportDelta.Digest(entries) };
            ExportDelta.AtomicWrite(Path.Combine(Root,"state.json"),ExportDelta.Json.Serialize(next)); State=next;
        }
        internal DeltaResult Apply(string file) {
            if(State==null) throw new Exception("請先選取基準聊天檔。");
            var fresh=ExportDelta.Parse(ExportDelta.Read(file)); var result=ExportDelta.Compare(State.Entries,fresh);
            if(result.Status!="matched") return result;
            string digest=ExportDelta.Digest(fresh);
            if(result.Added.Count>0) {
                string id=ExportDelta.Hash(State.Digest+":"+digest);
                string folder=Path.Combine(Root,"新增留言"); Directory.CreateDirectory(folder);
                string batch=Path.Combine(folder,id+".json");
                // Deterministic file name makes replay after a crash idempotent.
                if(!File.Exists(batch)) ExportDelta.AtomicWrite(batch,ExportDelta.Json.Serialize(new { ImportedAtUtc=DateTime.UtcNow.ToString("o"),BaseDigest=State.Digest,NewDigest=digest,Entries=result.Added,CompletenessVerified=false,OrdersCreated=0 }));
                ExportDelta.AtomicWrite(Path.Combine(folder,id+".txt"),ExportDelta.Render(result.Added));
                ExportDelta.AtomicWrite(Path.Combine(Root,"最新新增留言.txt"),ExportDelta.Render(result.Added));
            }
            // Do not shrink history on an identical suffix-only export: it weakens future alignment.
            if(result.Added.Count>0 || result.Overlap==State.Entries.Count) SaveState(fresh,State.TargetTitle);
            return result;
        }
    }
}
