Write-Host "Criando ambiente virtual..."
py -m venv .venv
Write-Host "Ativando ambiente virtual..."
& .\.venv\Scripts\Activate.ps1
Write-Host "Instalando dependencias..."
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
if (!(Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host "Arquivo .env criado. Edite ele antes de rodar o bot."
} else {
  Write-Host "Arquivo .env ja existe. Mantido sem alterar."
}
Write-Host "Pronto. Edite o .env e depois rode: .\run_once_windows.ps1"
