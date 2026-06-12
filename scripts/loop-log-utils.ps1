function Write-CompactLoopOutput {
    param(
        [AllowEmptyCollection()]
        [object[]]$OutputLines,
        [int]$TailLines = 80
    )

    if ($null -eq $OutputLines -or $OutputLines.Count -eq 0) {
        return
    }

    $patterns = @(
        'summary',
        'ERROR',
        'Error',
        'error',
        'FAILED',
        'Failed',
        'failed',
        'Traceback',
        'Exception',
        'captcha',
        'rate_limit',
        'unavailable'
    )
    $pattern = ($patterns -join '|')
    $important = @($OutputLines | Where-Object { [string]$_ -match $pattern })
    $tail = @($OutputLines | Select-Object -Last $TailLines)
    $emitted = New-Object System.Collections.Generic.HashSet[string]

    foreach ($line in @($important + $tail)) {
        $text = [string]$line
        if ($emitted.Add($text)) {
            Write-Output $text
        }
    }

    if ($OutputLines.Count -gt $emitted.Count) {
        Write-Output "[loop-log] compacted output original_lines=$($OutputLines.Count) emitted_lines=$($emitted.Count)"
    }
}
