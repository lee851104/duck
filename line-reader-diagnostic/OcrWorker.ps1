param(
    [Parameter(Mandatory=$true)][string]$ImagePath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$stream = $null
$bitmap = $null
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
    $null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
    $null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
        $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    function Await-WinRt($operation, [Type]$resultType) {
        $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
        if (-not $task.Wait(15000)) { throw 'Windows OCR operation timed out.' }
        return $task.Result
    }
    $languages = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
    $tag = $languages | Where-Object { $_ -match '^zh-(Hant|TW|HK)' } | Select-Object -First 1
    if (-not $tag) { throw 'Traditional Chinese Windows OCR language is not installed.' }
    $language = New-Object Windows.Globalization.Language($tag)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) { throw 'Cannot create Windows OCR engine.' }
    $file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($ImagePath))) ([Windows.Storage.StorageFile])
    $stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    if ($decoder.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $decoder.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {
        throw 'Image exceeds Windows OCR MaxImageDimension.'
    }
    $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $result = Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @($result.Lines | ForEach-Object {
        $line = $_
        $words = @($line.Words | ForEach-Object {
            [ordered]@{Text=$_.Text; X=$_.BoundingRect.X; Y=$_.BoundingRect.Y; Width=$_.BoundingRect.Width; Height=$_.BoundingRect.Height}
        })
        [ordered]@{Text=$line.Text; Words=$words}
    })
    $report = [ordered]@{
        Status='recognized'; Engine='Windows.Media.Ocr'; Language=$tag; ImagePath=[IO.Path]::GetFullPath($ImagePath)
        Width=$bitmap.PixelWidth; Height=$bitmap.PixelHeight; OcrElapsedMs=$watch.ElapsedMilliseconds
        Text=($lines.Text -join "`r`n"); Lines=$lines; CompletenessVerified=$false; OrdersCreated=0
    }
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath), ($report | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
} catch {
    $report = [ordered]@{Status='failed'; Error=$_.Exception.Message; CompletenessVerified=$false; OrdersCreated=0}
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath), ($report | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    exit 1
} finally {
    if ($null -ne $bitmap) { $bitmap.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
}
