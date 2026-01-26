# --- README.md ---
# KnetX SoftPLC (MVP)


## Avvio rapido (Windows)


### 1) Attiva venv
```powershell
cd C:\SplKnetx
.\knetxenv313\Scripts\Activate.ps1
```


### 2) Avvia LocalSim (runtime SIM)
```powershell
python .\knetx_runtime_sim.py
```


### 3) Avvia Sim Control GUI
In un'altra shell:
```powershell
python .\knetx_sim_control.py
```


## File
- `knetx_runtime_sim.py` : runtime SIM TCP (porta 1963)
- `knetx_client_ping.py` : client test comandi base
- `knetx_sim_control.py` : GUI Start/Stop/Run/Shutdown per LocalSim