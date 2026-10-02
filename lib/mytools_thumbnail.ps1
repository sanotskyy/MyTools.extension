<#
mytools_thumbnail.ps1
Витягує прев'ю (thumbnail) файлів так само, як їх показує Windows Explorer,
через Windows Shell (IShellItemImageFactory) — не відкриваючи сам файл.
Для .rfa це той самий wireframe/рендер, що реєструє інсталятор Revit.

Виклик:
    powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File mytools_thumbnail.ps1 <request.json> <outDir> <size>

request.json: [ { "index": 0, "path": "C:\...\Family.rfa" }, ... ]
Результат: у <outDir> з'являються файли "<index>.png" для тих, для кого вдалось
отримати прев'ю. Відсутність файлу означає, що прев'ю недоступне (не помилка).
#>
param(
    [Parameter(Mandatory = $true)][string]$RequestFile,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Size = 128
)

$ErrorActionPreference = 'SilentlyContinue'

$csharp = @"
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace MyToolsThumb
{
    [ComImport]
    [Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItem
    {
        void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
        void GetParent(out IShellItem ppsi);
        void GetDisplayName(int sigdnName, out IntPtr ppszName);
        void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
        void Compare(IShellItem psi, uint hint, out int piOrder);
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct SIZE
    {
        public int cx;
        public int cy;
    }

    [ComImport]
    [Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItemImageFactory
    {
        void GetImage(SIZE size, int flags, out IntPtr phbm);
    }

    public static class NativeMethods
    {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
        public static extern void SHCreateItemFromParsingName(
            string path, IntPtr pbc, ref Guid riid,
            [MarshalAs(UnmanagedType.Interface)] out IShellItemImageFactory ppv);

        [DllImport("gdi32.dll")]
        public static extern bool DeleteObject(IntPtr hObject);
    }

    public static class ThumbnailExtractor
    {
        // SIIGBF_RESIZETOFIT = 0x00 : кешоване прев'ю або згенероване одразу
        public static bool Save(string path, string outPngPath, int size)
        {
            try
            {
                Guid iidFactory = new Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b");
                IShellItemImageFactory factory = null;
                NativeMethods.SHCreateItemFromParsingName(path, IntPtr.Zero, ref iidFactory, out factory);
                if (factory == null) return false;

                SIZE sz;
                sz.cx = size;
                sz.cy = size;

                IntPtr hBmp = IntPtr.Zero;
                factory.GetImage(sz, 0, out hBmp);
                if (hBmp == IntPtr.Zero) return false;

                try
                {
                    using (Bitmap bmp = Bitmap.FromHbitmap(hBmp))
                    {
                        bmp.Save(outPngPath, ImageFormat.Png);
                    }
                }
                finally
                {
                    NativeMethods.DeleteObject(hBmp);
                }
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
"@

Add-Type -TypeDefinition $csharp -ReferencedAssemblies System.Drawing

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

# Файл запиту пишеться з UTF-8 BOM з боку Python — читаємо -Raw,
# BOM дозволяє автовизначити кодування коректно і в Windows PowerShell 5.1, і в 7+.
$jsonText = Get-Content -LiteralPath $RequestFile -Raw
$requests = $jsonText | ConvertFrom-Json

foreach ($r in $requests) {
    $idx  = $r.index
    $path = $r.path
    if ([string]::IsNullOrEmpty($path)) { continue }
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $outPng = Join-Path $OutDir ("{0}.png" -f $idx)
    [MyToolsThumb.ThumbnailExtractor]::Save($path, $outPng, $Size) | Out-Null
}
