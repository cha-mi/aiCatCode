# Debug: list all desktop icon names + positions
$code = @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.IO;

public class DesktopIconDebug
{
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string w);
    [DllImport("user32.dll")] public static extern IntPtr FindWindowEx(IntPtr p, IntPtr a, string c, string w);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a, bool i, uint pid);
    [DllImport("kernel32.dll")] public static extern IntPtr VirtualAllocEx(IntPtr p, IntPtr a, uint s, uint t, uint p2);
    [DllImport("kernel32.dll")] public static extern bool VirtualFreeEx(IntPtr p, IntPtr a, uint s, uint t);
    [DllImport("kernel32.dll")] public static extern bool WriteProcessMemory(IntPtr p, IntPtr b, IntPtr buf, uint n, out int w);
    [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr p, IntPtr b, byte[] buf, uint n, out int r);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)] public struct LVITEM {
        public uint mask; public int iItem; public int iSubItem; public uint state; public uint stateMask;
        public IntPtr pszText; public int cchTextMax; public int iImage; public IntPtr lParam;
    }
    public const uint LVM_FIRST=0x1000, LVM_GETITEMCOUNT=LVM_FIRST+4, LVM_GETITEMTEXTW=LVM_FIRST+115,
                        LVM_GETITEMPOSITION=LVM_FIRST+16, LVIF_TEXT=0x0001;
    public const uint PROCESS_VM_READ=0x0010, PROCESS_VM_WRITE=0x0020, PROCESS_VM_OPERATION=0x0008,
                        MEM_COMMIT=0x1000, MEM_RELEASE=0x8000, PAGE_READWRITE=0x04;
    static IntPtr _found = IntPtr.Zero;
    static bool Cb(IntPtr h, IntPtr l) {
        StringBuilder sb = new StringBuilder(256);
        GetClassName(h, sb, 256);
        if (sb.ToString() == "SHELLDLL_DefView") { _found = h; return false; }
        return true;
    }
    static IntPtr FindDefView() {
        IntPtr progman = FindWindow("Progman", null);
        if (progman != IntPtr.Zero) {
            IntPtr dv = FindWindowEx(progman, IntPtr.Zero, "SHELLDLL_DefView", null);
            if (dv != IntPtr.Zero) return dv;
        }
        _found = IntPtr.Zero;
        EnumWindows(new EnumWindowsProc(Cb), IntPtr.Zero);
        if (_found != IntPtr.Zero) return _found;
        IntPtr w = IntPtr.Zero;
        do { w = FindWindowEx(IntPtr.Zero, w, "WorkerW", null);
             if (w != IntPtr.Zero) { IntPtr dv = FindWindowEx(w, IntPtr.Zero, "SHELLDLL_DefView", null); if (dv != IntPtr.Zero) return dv; }
        } while (w != IntPtr.Zero);
        return IntPtr.Zero;
    }
    public static string ListAll() {
        IntPtr dv = FindDefView();
        if (dv == IntPtr.Zero) return "NO_DEFVIEW";
        IntPtr lv = FindWindowEx(dv, IntPtr.Zero, "SysListView32", "FolderView");
        if (lv == IntPtr.Zero) lv = FindWindowEx(dv, IntPtr.Zero, "SysListView32", null);
        if (lv == IntPtr.Zero) return "NO_LISTVIEW";
        uint pid; GetWindowThreadProcessId(lv, out pid);
        IntPtr hp = OpenProcess(PROCESS_VM_READ|PROCESS_VM_WRITE|PROCESS_VM_OPERATION, false, pid);
        if (hp == IntPtr.Zero) return "NO_PROCESS";
        int count = (int)SendMessage(lv, LVM_GETITEMCOUNT, IntPtr.Zero, IntPtr.Zero);
        int bufSize = 4096;
        IntPtr pText = VirtualAllocEx(hp, IntPtr.Zero, (uint)bufSize, MEM_COMMIT, PAGE_READWRITE);
        IntPtr pItem = VirtualAllocEx(hp, IntPtr.Zero, (uint)Marshal.SizeOf(typeof(LVITEM)), MEM_COMMIT, PAGE_READWRITE);
        IntPtr pPoint = VirtualAllocEx(hp, IntPtr.Zero, 8, MEM_COMMIT, PAGE_READWRITE);
        try {
            var sb = new StringBuilder();
            sb.Append("count=").Append(count).AppendLine();
            byte[] localBuf = new byte[bufSize];
            byte[] pointBuf = new byte[8];
            for (int i = 0; i < count; i++) {
                LVITEM lvi = new LVITEM(); lvi.mask = LVIF_TEXT; lvi.iItem = i; lvi.iSubItem = 0;
                lvi.cchTextMax = bufSize/2; lvi.pszText = pText;
                int written;
                IntPtr pLocalItem = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(LVITEM)));
                Marshal.StructureToPtr(lvi, pLocalItem, false);
                WriteProcessMemory(hp, pItem, pLocalItem, (uint)Marshal.SizeOf(typeof(LVITEM)), out written);
                Marshal.FreeHGlobal(pLocalItem);
                IntPtr res = SendMessage(lv, LVM_GETITEMTEXTW, (IntPtr)i, pItem);
                int charsCopied = res.ToInt32();
                int br;
                ReadProcessMemory(hp, pText, localBuf, (uint)bufSize, out br);
                int validBytes = Math.Min(br, Math.Max(0, charsCopied * 2));
                string name = validBytes > 0 ? Encoding.Unicode.GetString(localBuf, 0, validBytes).Trim('\0') : "";
                SendMessage(lv, LVM_GETITEMPOSITION, (IntPtr)i, pPoint);
                ReadProcessMemory(hp, pPoint, pointBuf, 8, out br);
                int x = BitConverter.ToInt32(pointBuf, 0);
                int y = BitConverter.ToInt32(pointBuf, 4);
                sb.Append(i).Append("|").Append(name).Append("|").Append(x).Append(",").Append(y).AppendLine();
            }
            return sb.ToString();
        } finally {
            if (pText != IntPtr.Zero) VirtualFreeEx(hp, pText, 0, MEM_RELEASE);
            if (pItem != IntPtr.Zero) VirtualFreeEx(hp, pItem, 0, MEM_RELEASE);
            if (pPoint != IntPtr.Zero) VirtualFreeEx(hp, pPoint, 0, MEM_RELEASE);
            if (hp != IntPtr.Zero) CloseHandle(hp);
        }
    }
}
"@
Add-Type -TypeDefinition $code -Language CSharp
Write-Output ([DesktopIconDebug]::ListAll())
