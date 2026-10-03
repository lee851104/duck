using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;

namespace LineExportMonitor
{
    internal static class ExportTests
    {
        private static List<ChatEntry> Entries(params string[] text) {return text.Select(s=>new ChatEntry{Date="2026-10-03",Time="10:00",Raw="10:00 "+s}).ToList();}
        internal static void Run(string source,string output)
        {
            var passed=new List<string>();Action<bool,string> check=(ok,name)=>{if(!ok)throw new Exception("FAILED: "+name);passed.Add(name);};
            var multiline=ExportDelta.Parse("2026.10.03 星期六\r\n10:00 Mary Jane 葡萄 +1\r\n青菜*2\r\n備註保留\r\n10:00 Mary Jane 葡萄 +1\r\n");
            check(multiline.Count==2&&multiline[0].Raw.Contains("青菜*2\n備註保留"),"multiline content and name spacing retained");
            var same=ExportDelta.Compare(multiline,multiline);check(same.Status=="matched"&&same.Added.Count==0,"identical export adds nothing");
            var repeated=Entries("甲 +1","甲 +1");var added=ExportDelta.Compare(repeated,Entries("甲 +1","甲 +1","甲 +1"));
            check(added.Added.Count==1,"same minute same author same text appended is retained");
            added=ExportDelta.Compare(Entries("甲 +1"),Entries("甲 +1","乙 +1"));check(added.Added.Count==1&&added.Added[0].Raw.Contains("乙"),"different customers identical quantity retained");
            var old=Entries("A","B","C","D","E");
            var tail=ExportDelta.Compare(old,Entries("C","D","E","F"));check(tail.Status=="matched"&&tail.Overlap==3&&tail.Added.Count==1,"shifted export aligns ordered overlap");
            check(ExportDelta.Compare(old,Entries("D","E","F")).Status=="review_required","insufficient overlap held");
            check(ExportDelta.Compare(old,Entries("A","B")).Status=="review_required","older shortened snapshot held");
            check(ExportDelta.Compare(old,Entries("A","changed","C","D","E","F")).Status=="review_required","edited or recalled record held");
            check(ExportDelta.Compare(Entries("A","B","C","A","B","C"),Entries("A","B","C","Z")).Status=="review_required","ambiguous repeated sequence held");
            check(ExportDelta.Compare(old,Entries("X","Y","Z")).Status=="review_required","unrelated history rejected");
            bool error=false;try{ExportDelta.Parse("arbitrary text");}catch{error=true;}check(error,"malformed export rejected");
            var real=ExportDelta.Parse(ExportDelta.Read(source));check(real.Count>1000,"actual supplied LINE export parsed");
            string root=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(output)),"export-tests-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
            string originalCopy=Path.Combine(root,"original.txt");File.Copy(source,originalCopy);
            var store=new DeltaStore(Path.Combine(root,"state"));store.Initialize(originalCopy,"測試社群");string before=File.ReadAllText(Path.Combine(store.Root,"state.json"));
            check(!Directory.Exists(Path.Combine(store.Root,"新增留言")),"initial baseline does not reimport historical orders");
            string fresh=Path.Combine(root,"fresh.txt");File.WriteAllText(fresh,ExportDelta.Read(source)+"\r\n2026.10.03 星期六\r\n10:00 測試客人 葡萄 +1\r\n10:00 測試客人 葡萄 +1\r\n",ExportDelta.Utf8);
            var result=store.Apply(fresh);check(result.Added.Count==2,"real history plus two synthetic additions yields exactly two");
            check(store.Apply(fresh).Added.Count==0,"repeat processing idempotent");
            check(new DeltaStore(store.Root).Apply(fresh).Added.Count==0,"restart preserves baseline");
            // Replay a crash after batch publication but before state replacement.
            ExportDelta.AtomicWrite(Path.Combine(store.Root,"state.json"),before);store=new DeltaStore(store.Root);store.Apply(fresh);
            check(Directory.GetFiles(Path.Combine(store.Root,"新增留言"),"*.json").Length==1,"crash replay does not duplicate output batch");
            string stateBefore=File.ReadAllText(Path.Combine(store.Root,"state.json"));string broken=Path.Combine(root,"broken.txt");File.WriteAllText(broken,"2026.10.03 星期六\n10:00 Unrelated message\n",ExportDelta.Utf8);
            check(store.Apply(broken).Status=="review_required"&&File.ReadAllText(Path.Combine(store.Root,"state.json"))==stateBefore,"uncertain alignment preserves previous state");
            check(File.Exists(originalCopy)&&ExportDelta.Read(originalCopy)==ExportDelta.Read(source),"original export left unchanged");
            string work=Path.Combine(root,"work");Directory.CreateDirectory(work);string owned=Path.Combine(work,"incoming-"+Guid.NewGuid().ToString("N")+".txt");File.WriteAllText(owned,"owned",ExportDelta.Utf8);ExportAutomation.RemoveSuccessfulInput(owned,work);check(!File.Exists(owned),"only generated successful input can be removed");
            error=false;try{ExportAutomation.RemoveSuccessfulInput(originalCopy,work);}catch{error=true;}check(error&&File.Exists(originalCopy),"cleanup rejects external original file");
            string mock="{\"Status\":\"recognized\",\"Scale\":2,\"Lines\":[{\"Text\":\"儲 存 聊 天\",\"Words\":[{\"X\":820,\"Y\":700,\"Width\":140,\"Height\":36}]}]}";
            var label=ExportAutomation.FindSaveLabel(mock,new Size(550,700),new Point(419,40));check(label==new Rectangle(410,350,70,18),"menu OCR coordinates mapped to source pixels");
            error=false;try{ExportAutomation.FindSaveLabel(mock.Replace("儲 存 聊 天","退 出"),new Size(550,700),new Point(419,40));}catch{error=true;}check(error,"wrong menu label never accepted");
            string sample=Path.Combine(LineOcrMonitor.Ocr.Root,".qa","export-menu-sample.ocr.json");
            if(File.Exists(sample)){var data=ExportDelta.Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(sample));var rect=ExportAutomation.FindSaveLabel(File.ReadAllText(sample),new Size(Convert.ToInt32(data["OriginalWidth"]),Convert.ToInt32(data["OriginalHeight"])),new Point(419,44));check(rect.Width>20,"actual provided menu screenshot identifies save-chat label");}
            File.WriteAllText(output,ExportDelta.Json.Serialize(new {Passed=passed.Count,Tests=passed,RealExportEntries=real.Count,FirstDate=real.First().Date,LastDate=real.Last().Date,SyntheticNewEntries=2,LiveLineUiTested=false,FixtureDirectory=root}),ExportDelta.Utf8);
        }
    }
}
