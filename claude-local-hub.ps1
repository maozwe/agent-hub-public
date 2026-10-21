$ErrorActionPreference = 'Stop'
$Wrapper = Join-Path $env:USERPROFILE 'bin/claude-local.ps1'
$McpConfig = Join-Path $PSScriptRoot '.local/claude-local-mcp.json'
$Instructions = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'AGENT-HUB-PROMPT.he.md') -Raw -Encoding UTF8
& $Wrapper --mcp-config $McpConfig --append-system-prompt $Instructions @args
exit $LASTEXITCODE
