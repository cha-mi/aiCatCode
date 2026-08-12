# Read desktop ListView icon positions via cross-process LVM messages
# Input: environment variable ANQI_FILE_PATH = absolute path of target file
# Output: JSON

$FilePath = $env:ANQI_FILE_PATH

$targetFullName = [System.IO.Path]::GetFileName($FilePath)
$targetStem     = [System.IO.Path]::GetFileNameWithoutExtension($FilePath)

$code = @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.IO;

public class DesktopIconFinder
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

    // Find SHELLDLL_DefView by enumerating all top-level and child windows
    static IntPtr _foundDefView = IntPtr.Zero;

    static bool EnumWindowsCallback(IntPtr hWnd, IntPtr lParam)
    {
        StringBuilder sb = new StringBuilder(256);
        GetClassName(hWnd, sb, 256);
        if (sb.ToString() == "SHELLDLL_DefView")
        {
            _foundDefView = hWnd;
            return false; // stop enumeration
        }
        return true;
    }

    [DllImport("user32.dll", CharSet=CharSet.Auto)]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    static IntPtr FindDefView()
    {
        // Method 1: Progman -> SHELLDLL_DefView
        IntPtr progman = FindWindow("Progman", null);
        if (progman != IntPtr.Zero)
        {
            IntPtr dv = FindWindowEx(progman, IntPtr.Zero, "SHELLDLL_DefView", null);
            if (dv != IntPtr.Zero) return dv;
        }

        // Method 2: Enumerate ALL top-level windows looking for SHELLDLL_DefView
        _foundDefView = IntPtr.Zero;
        EnumWindows(new EnumWindowsProc(EnumWindowsCallback), IntPtr.Zero);
        if (_foundDefView != IntPtr.Zero) return _foundDefView;

        // Method 3: Enumerate child windows of Progman and all WorkerW windows
        if (progman != IntPtr.Zero)
        {
            _foundDefView = IntPtr.Zero;
            EnumChildWindows(progman, new EnumWindowsProc(EnumWindowsCallback), IntPtr.Zero);
            if (_foundDefView != IntPtr.Zero) return _foundDefView;
        }

        // Method 4: Find all WorkerW top-level windows and check their children
        IntPtr w = IntPtr.Zero;
        do
        {
            w = FindWindowEx(IntPtr.Zero, w, "WorkerW", null);
            if (w != IntPtr.Zero)
            {
                IntPtr dv = FindWindowEx(w, IntPtr.Zero, "SHELLDLL_DefView", null);
                if (dv != IntPtr.Zero) return dv;
                _foundDefView = IntPtr.Zero;
                EnumChildWindows(w, new EnumWindowsProc(EnumWindowsCallback), IntPtr.Zero);
                if (_foundDefView != IntPtr.Zero) return _foundDefView;
            }
        } while (w != IntPtr.Zero);

        return IntPtr.Zero;
    }

    // Returns: FOUND|x|y|match|lvname   or   NOPE|reason
    public static string FindIcon(string tFull, string tStem)
    {
        IntPtr defView = FindDefView();
        if (defView == IntPtr.Zero) return "NOPE|NO_DEFVIEW";
        IntPtr lv = FindWindowEx(defView, IntPtr.Zero, "SysListView32", "FolderView");
        if (lv == IntPtr.Zero) lv = FindWindowEx(defView, IntPtr.Zero, "SysListView32", null);
        if (lv == IntPtr.Zero) return "NOPE|NO_LISTVIEW";
        uint pid; GetWindowThreadProcessId(lv, out pid);
        IntPtr hp = OpenProcess(PROCESS_VM_READ|PROCESS_VM_WRITE|PROCESS_VM_OPERATION, false, pid);
        if (hp == IntPtr.Zero) return "NOPE|NO_PROCESS";
        int count = (int)SendMessage(lv, LVM_GETITEMCOUNT, IntPtr.Zero, IntPtr.Zero);
        int bufSize = 4096;
        IntPtr pText = VirtualAllocEx(hp, IntPtr.Zero, (uint)bufSize, MEM_COMMIT, PAGE_READWRITE);
        IntPtr pItem = VirtualAllocEx(hp, IntPtr.Zero, (uint)Marshal.SizeOf(typeof(LVITEM)), MEM_COMMIT, PAGE_READWRITE);
        IntPtr pPoint = VirtualAllocEx(hp, IntPtr.Zero, 8, MEM_COMMIT, PAGE_READWRITE);
        try {
            byte[] localBuf = new byte[bufSize];
            byte[] pointBuf = new byte[8];
            int foundBy = 0;
            for (int pass = 1; pass <= 3 && foundBy == 0; pass++) {
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
                    if (charsCopied <= 0) continue;
                    int br;
                    ReadProcessMemory(hp, pText, localBuf, (uint)bufSize, out br);
                    int validBytes = Math.Min(br, charsCopied * 2);
                    if (validBytes <= 0) continue;
                    string text = Encoding.Unicode.GetString(localBuf, 0, validBytes).Trim('\0');
                    bool match = false;
                    if (pass == 1) {
                        match = text.Equals(tFull, StringComparison.OrdinalIgnoreCase);
                        if (match) foundBy = 1;
                    } else if (pass == 2) {
                        string s = Path.GetFileNameWithoutExtension(text);
                        match = s.Equals(tStem, StringComparison.OrdinalIgnoreCase);
                        if (match) foundBy = 2;
                    } else {
                        string s = text.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase)
                                    ? Path.GetFileNameWithoutExtension(text)
                                    : text;
                        match = s.Equals(tStem, StringComparison.OrdinalIgnoreCase);
                        if (match) foundBy = 3;
                    }
                    if (match) {
                        SendMessage(lv, LVM_GETITEMPOSITION, (IntPtr)i, pPoint);
                        int br2;
                        ReadProcessMemory(hp, pPoint, pointBuf, 8, out br2);
                        int x = BitConverter.ToInt32(pointBuf, 0);
                        int y = BitConverter.ToInt32(pointBuf, 4);
                        string safeName = text.Replace("|", "\u2223");
                        return "FOUND|" + x + "|" + y + "|" + foundBy + "|" + safeName;
                    }
                }
            }
            return "NOPE|NO_MATCH";
        } finally {
            if (pText != IntPtr.Zero) VirtualFreeEx(hp, pText, 0, MEM_RELEASE);
            if (pItem != IntPtr.Zero) VirtualFreeEx(hp, pItem, 0, MEM_RELEASE);
            if (pPoint != IntPtr.Zero) VirtualFreeEx(hp, pPoint, 0, MEM_RELEASE);
            if (hp != IntPtr.Zero) CloseHandle(hp);
        }
    }
}
"@

try {
    Add-Type -TypeDefinition $code -Language CSharp
    $raw = [DesktopIconFinder]::FindIcon($targetFullName, $targetStem)
    if ($raw.StartsWith('FOUND|')) {
        $parts = $raw.Split('|')
        $obj = [ordered]@{
            found = $true
            x     = [int]$parts[1]
            y     = [int]$parts[2]
            match = [int]$parts[3]
            lvname = $parts[4]
        }
        $obj | ConvertTo-Json -Compress
    } else {
        $reason = $raw.Substring(5)
        $obj = [ordered]@{ found = $false; reason = $reason }
        $obj | ConvertTo-Json -Compress
    }
} catch {
    $obj = [ordered]@{
        found  = $false
        reason = 'SCRIPT_ERR'
        error  = $_.Exception.Message
    }
    $obj | ConvertTo-Json -Compress
}
