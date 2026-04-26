# Windows Speech Synthesis Script
# Usage: .\say.ps1 "Your message here"

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Message
)

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0  # Range: -10 (slow) to 10 (fast)

Write-Host "Speaking: $Message" -ForegroundColor Cyan
$synth.Speak($Message)
