# iBOM login redirect chain probe (phase 0B). Windows PowerShell 5.1, no install needed.
#
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File ibom_sso_chain.ps1
#   or: open PowerShell, paste the whole file, press Enter.
# Output: <Downloads>\ibom_sso_chain_<time>.json
#
# Visits iBOM WITHOUT logging in: no username/password is sent, Windows integrated
# authentication is NOT used (UseDefaultCredentials stays false). Records each redirect
# hop (host, path, query parameter names), cookie NAMES (never values), the login form
# action and field names, and login-related API paths found in iBOM front-end scripts.
# One-time values (state, code, nonce, session_code, ticket ...) are never recorded.

$ErrorActionPreference = 'Stop'
$ScriptVersion = '2026-11-20.1'
$Origin = 'https://ibom.sgmw.com.cn'
$MaxHops = 15
$MaxScripts = 12
$MaxScriptBytes = 6MB
$TimeoutMs = 20000

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$SafeKeys = @('client_id','response_type','scope','response_mode','kc_idp_hint','ui_locales','prompt','loginType','logintype','lang','locale')
$RedirectKeys = @('redirect_uri','service','returnUrl','returnurl','redirect','target')

function Get-QueryPairs([string]$query) {
    $pairs = @()
    if (-not $query) { return $pairs }
    foreach ($part in $query.TrimStart('?').Split('&')) {
        if (-not $part) { continue }
        $kv = $part.Split('=', 2)
        $name = [Uri]::UnescapeDataString($kv[0])
        $value = if ($kv.Length -gt 1) { [Uri]::UnescapeDataString($kv[1].Replace('+', ' ')) } else { '' }
        $pairs += [pscustomobject]@{ n = $name; v = $value }
    }
    return $pairs
}

function Format-RedirectValue([string]$value) {
    try {
        $u = [Uri]$value
        $names = @(Get-QueryPairs $u.Query | ForEach-Object { $_.n + '=...' })
        $tail = if ($names.Count -gt 0) { '?' + ($names -join '&') } else { '' }
        return $u.Scheme + '://' + $u.Host + $u.AbsolutePath + $tail
    } catch { return '<unparsable>' }
}

function Get-SafeUrl([string]$url) {
    $u = [Uri]$url
    $query = @()
    foreach ($p in @(Get-QueryPairs $u.Query)) {
        $name = $p.n; $value = '<omitted>'
        if ($SafeKeys -contains $name) { $value = $p.v }
        if ($RedirectKeys -contains $name) { $value = Format-RedirectValue $p.v }
        $query += [ordered]@{ name = $name; value = $value }
    }
    return [ordered]@{ scheme = $u.Scheme; host = $u.Host; port = $u.Port; path = $u.AbsolutePath; query = $query }
}

function Get-CookieNames($headers) {
    $out = @()
    $raw = $headers.GetValues('Set-Cookie')
    if (-not $raw) { return $out }
    foreach ($item in $raw) {
        $name = $item.Split('=', 2)[0].Trim()
        if (-not $name -or $name -match '\s') { continue }  # fragments of Expires dates split on commas
        $flags = @($item.Split(';') | Select-Object -Skip 1 | ForEach-Object { $_.Trim().Split('=')[0].ToLower() } |
            Where-Object { @('httponly','secure','samesite','domain','path') -contains $_ } | Sort-Object -Unique)
        $out += [ordered]@{ name = $name; flags = $flags }
    }
    return $out
}

function Invoke-Hop([string]$url, $cookies, [int]$maxBytes) {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.Method = 'GET'
    $req.AllowAutoRedirect = $false
    $req.UseDefaultCredentials = $false
    $req.CookieContainer = $cookies
    $req.Timeout = $TimeoutMs
    $req.ReadWriteTimeout = $TimeoutMs
    $req.UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) vse-toolbox-phase0b'
    $req.Headers.Add('Accept-Language', 'zh-CN')
    $proxy = [Net.WebRequest]::GetSystemWebProxy()
    $proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials  # proxy only, never the target site
    $req.Proxy = $proxy
    $resp = $null
    try { $resp = $req.GetResponse() }
    catch [Net.WebException] {
        if ($_.Exception.Response) { $resp = $_.Exception.Response } else { throw }
    }
    $body = ''
    $ctype = [string]$resp.ContentType
    if ($ctype -match 'html|json|javascript|text') {
        $stream = $resp.GetResponseStream()
        $buffer = New-Object byte[] $maxBytes
        $total = 0
        while ($total -lt $maxBytes) {
            $n = $stream.Read($buffer, $total, [Math]::Min(65536, $maxBytes - $total))
            if ($n -le 0) { break }
            $total += $n
        }
        $body = [Text.Encoding]::UTF8.GetString($buffer, 0, $total)
    }
    # Note: piping $null into ForEach-Object still runs the block once, so guard explicitly.
    $authSchemes = @()
    $authRaw = $resp.Headers.GetValues('WWW-Authenticate')
    if ($authRaw) { foreach ($x in $authRaw) { if ($x) { $authSchemes += $x.Split(' ')[0] } } }
    $result = [ordered]@{
        status = [int]$resp.StatusCode
        contentType = $ctype
        location = $resp.Headers['Location']
        server = $resp.Headers['Server']
        wwwAuthenticate = $authSchemes
        setCookies = Get-CookieNames $resp.Headers
        body = $body
    }
    $resp.Close()
    return $result
}

function Get-PageInfo([string]$html, [string]$baseUrl) {
    $base = [Uri]$baseUrl
    $forms = @()
    foreach ($m in [regex]::Matches($html, '(?is)<form\b([^>]*)>(.*?)</form>')) {
        $attrs = $m.Groups[1].Value
        $action = ''; $method = 'get'
        $a = [regex]::Match($attrs, '(?i)action\s*=\s*["'']([^"'']*)["'']'); if ($a.Success) { $action = [Net.WebUtility]::HtmlDecode($a.Groups[1].Value) }
        $mm = [regex]::Match($attrs, '(?i)method\s*=\s*["'']?(\w+)'); if ($mm.Success) { $method = $mm.Groups[1].Value.ToLower() }
        $fields = @()
        foreach ($f in [regex]::Matches($m.Groups[2].Value, '(?i)<(input|select|button)\b([^>]*)>')) {
            $n = [regex]::Match($f.Groups[2].Value, '(?i)\bname\s*=\s*["'']([^"'']+)["'']')
            $t = [regex]::Match($f.Groups[2].Value, '(?i)\btype\s*=\s*["'']?(\w+)')
            if ($n.Success) { $fields += [ordered]@{ name = $n.Groups[1].Value; type = $(if ($t.Success) { $t.Groups[1].Value } else { $f.Groups[1].Value }) } }
        }
        $actionInfo = $null
        if ($action) { $actionInfo = Get-SafeUrl ([Uri]::new($base, $action)).AbsoluteUri }
        $forms += [ordered]@{ action = $actionInfo; method = $method; fields = $fields }
    }
    $scripts = @([regex]::Matches($html, '(?i)<script\b[^>]*\bsrc\s*=\s*["'']([^"'']+)["'']') | ForEach-Object { ([Uri]::new($base, $_.Groups[1].Value)).AbsoluteUri } | Select-Object -First $MaxScripts)
    $title = ''
    $tm = [regex]::Match($html, '(?is)<title>(.*?)</title>'); if ($tm.Success) { $title = $tm.Groups[1].Value.Trim() }
    $jsRedirects = @([regex]::Matches($html, '(?i)(?:location\.href|window\.location)\s*=\s*["'']([^"'']{1,200})') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique -First 5)
    return [ordered]@{ title = $title; forms = $forms; scripts = $scripts; jsRedirects = $jsRedirects }
}

function Trace-Chain([string]$start) {
    $cookies = New-Object Net.CookieContainer
    $hops = @()
    $url = $start
    $page = $null
    for ($i = 0; $i -lt $MaxHops; $i++) {
        try { $r = Invoke-Hop $url $cookies 2000000 }
        catch { $hops += [ordered]@{ url = (Get-SafeUrl $url); error = $_.Exception.GetType().Name + ': ' + $_.Exception.Message + ' (line ' + $_.InvocationInfo.ScriptLineNumber + ')' }; break }
        $hop = [ordered]@{ url = (Get-SafeUrl $url); status = $r.status; contentType = $r.contentType; server = $r.server; wwwAuthenticate = $r.wwwAuthenticate; setCookies = $r.setCookies }
        if ($r.location) {
            $next = ([Uri]::new([Uri]$url, $r.location)).AbsoluteUri
            $hop.location = Get-SafeUrl $next
            $hops += $hop
            $url = $next
            continue
        }
        if ($r.contentType -match 'json') { $hop.bodyHead = $r.body.Substring(0, [Math]::Min(300, $r.body.Length)) }
        $hops += $hop
        if ($r.contentType -match 'html') { $page = Get-PageInfo $r.body $url }
        break
    }
    return [ordered]@{ start = $start; hops = $hops; finalPage = $page }
}

$patterns = @(
    'ssoAuth[A-Za-z/._-]*',
    '/fwSecurity/authentication/[A-Za-z]+\.api',
    '/fwPlatform/[A-Za-z]+/[A-Za-z]*[Ll]ogin[A-Za-z]*\.api',
    '[A-Za-z/]*login\.api',
    '/auth/realms/[A-Za-z0-9_-]+',
    'openid-connect/[a-z]+',
    'account\.sgmw\.com\.cn[^"''\s]*',
    'NORMAL_LOGIN|DEFAULT_SSO|CHOOSE_LOGIN_METHOD|SSO_CHECK_URL',
    'client_id["'']?\s*[:=]\s*["''][^"'']{1,60}["'']',
    '/cas/[a-zA-Z]+'
)

Write-Host '[1/3] Tracing iBOM home page (not logged in, no credentials sent)...'
$root = Trace-Chain ($Origin + '/')
Write-Host '[2/3] Tracing ssoAuth/login.api ...'
$sso = Trace-Chain ($Origin + '/fwPlatform/ssoAuth/login.api')

$scriptUrls = @()
foreach ($c in @($root, $sso)) { if ($c.finalPage) { $scriptUrls += $c.finalPage.scripts } }
if (-not ($scriptUrls | Where-Object { ([Uri]$_).Host -eq ([Uri]$Origin).Host })) {
    try {
        $homePage = Invoke-Hop ($Origin + '/') (New-Object Net.CookieContainer) 2000000
        if ($homePage.contentType -match 'html') { $scriptUrls += (Get-PageInfo $homePage.body ($Origin + '/')).scripts }
    } catch { }
}
$scriptUrls = @($scriptUrls | Select-Object -Unique -First $MaxScripts)

Write-Host '[3/3] Searching iBOM front-end scripts for login endpoints...'
$fetched = @()
$hits = [ordered]@{}
foreach ($s in $scriptUrls) {
    if (([Uri]$s).Host -ne ([Uri]$Origin).Host) { $fetched += [ordered]@{ url = (Get-SafeUrl $s); skipped = 'not iBOM host' }; continue }
    try { $r = Invoke-Hop $s (New-Object Net.CookieContainer) $MaxScriptBytes }
    catch { $fetched += [ordered]@{ url = (Get-SafeUrl $s); error = $_.Exception.GetType().Name }; continue }
    $fetched += [ordered]@{ url = (Get-SafeUrl $s); status = $r.status; chars = $r.body.Length }
    foreach ($p in $patterns) {
        $list = @(); if ($hits.Contains($p)) { $list = @($hits[$p]) }
        foreach ($m in [regex]::Matches($r.body, $p)) {
            if ($list.Count -ge 8) { break }
            $st = [Math]::Max(0, $m.Index - 60)
            $len = [Math]::Min($r.body.Length - $st, $m.Length + 120)
            $snip = $r.body.Substring($st, $len).Replace("`n", ' ').Replace("`r", ' ')
            if ($list -notcontains $snip) { $list += $snip }
        }
        if ($list.Count -gt 0) { $hits[$p] = $list }
    }
}

$report = [ordered]@{
    scriptVersion = $ScriptVersion
    collectedAt = (Get-Date).ToUniversalTime().ToString('o')
    powershell = $PSVersionTable.PSVersion.ToString()
    os = [Environment]::OSVersion.VersionString
    rootChain = $root
    ssoAuthChain = $sso
    frontendScripts = [ordered]@{ scripts = $fetched; hits = $hits }
}

$downloads = Join-Path $env:USERPROFILE 'Downloads'
if (-not (Test-Path $downloads)) { $downloads = (Get-Location).Path }
$outFile = Join-Path $downloads ('ibom_sso_chain_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.json')
$report | ConvertTo-Json -Depth 10 | Out-File -FilePath $outFile -Encoding UTF8
Write-Host ('Done: ' + $outFile)
Write-Host 'Please send this file back. It contains no password, token or cookie value.'
