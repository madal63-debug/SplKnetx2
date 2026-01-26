# KnetX SoftPLC (MVP)

## Avvio rapido (Windows)

### 1) Attiva venv
```powershell
cd C:\SplKnetx
.\knetxenv313\Scripts\Activate.ps1
```

### 2) Avvia LocalSim (runtime SIM)
```powershell
python .\runtime\localsim\knetx_runtime_sim.py
```

### 3) Avvia Sim Control GUI
In un'altra shell:
```powershell
python .\runtime\localsim\knetx_sim_control.py
```

### 4) Client test (PING/STATUS)
In un'altra shell:
```powershell
python .\tools\knetx_client_ping.py --cmd PING
python .\tools\knetx_client_ping.py --cmd GET_STATUS
```

## File
- `runtime/localsim/knetx_runtime_sim.py` : runtime SIM TCP (porta 1963)
- `tools/knetx_client_ping.py` : client test comandi base
- `runtime/localsim/knetx_sim_control.py` : GUI Start/Stop/Run/Shutdown per LocalSim
