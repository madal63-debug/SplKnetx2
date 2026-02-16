# COMMANDS AUDIT (totale)

Stato: audit completo dei comandi UI presenti in `ide/` + moduli UI in `runtime/` e `tools/`.

## Ambito scansionato

- `ide/` → **incluso interamente** (UI principale + dialog).
- `runtime/` → incluso solo `runtime/localsim/knetx_sim_control.py` (ha UI Qt).
- `tools/` → incluso solo `tools/knetx_new_project.py` (ha UI Qt).
- Esclusi perché non UI:
  - `runtime/localsim/knetx_runtime_sim.py`
  - `tools/knetx_client_ping.py`

---

## 1) IDE principale (`ide/main_window.py`)

## 1.1 Menu bar

### Menu `File`

| Comando UI | Handler | File + funzione | Shortcut |
|---|---|---|---|
| Nuovo progetto | `self.new_project` | `ide/main_window.py` → `MainWindow.new_project` | — |
| Apri progetto | `self.open_project` | `ide/main_window.py` → `MainWindow.open_project` | — |
| Chiudi progetto | `self.close_project` | `ide/main_window.py` → `MainWindow.close_project` | — |
| Salva | `self.save_current` | `ide/main_window.py` → `MainWindow.save_current` | `Ctrl+S` (`QKeySequence.Save`) |
| Salva tutto | `self.save_all` | `ide/main_window.py` → `MainWindow.save_all` | — |
| Salva con nome... | `self.save_project_as` | `ide/main_window.py` → `MainWindow.save_project_as` | — |
| Esci | `self.close` | `ide/main_window.py` → `QWidget.close` | — |

### Menu `Progetto`

| Comando UI | Handler | File + funzione | Shortcut |
|---|---|---|---|
| Aggiungi pagina | `self.add_page` | `ide/main_window.py` → `MainWindow.add_page` | — |
| Elimina progetto | `self.delete_project` | `ide/main_window.py` → `MainWindow.delete_project` | — |

## 1.2 Toolbar

Toolbar costruita in `_build_toolbar`.

| Azione (testo bottone) | Handler | File + funzione | Tooltip/testo |
|---|---|---|---|
| Settings | `lambda: self.tabs.setCurrentWidget(self.tab_settings)` oppure `show_settings` se presente | `ide/main_window.py` → `_build_toolbar` | tooltip esplicito **assente** (usa testo azione) |
| Connetti / Disconnetti (toggle testo) | `self.toggle_connect` | `ide/main_window.py` → `_build_toolbar`, `toggle_connect` | tooltip esplicito **assente** |
| Compila | `self.do_compile` / fallback `compile_project` / fallback `stub_compile` | `ide/main_window.py` → `_build_toolbar` | tooltip esplicito **assente** |
| Send | `self.do_send` / fallback `send_project` / fallback `stub_download` | `ide/main_window.py` → `_build_toolbar` | tooltip esplicito **assente** |

> Nota: non ci sono `setToolTip()` espliciti sulle `QAction` della toolbar.

## 1.3 Context menu

### Albero sinistro (`QTreeWidget` progetto)

Definito in `MainWindow.on_tree_context_menu`.

| Nodo/area | Voci | Handler |
|---|---|---|
| `PAGES_ROOT` | Nuova pagina | `self.add_page` |
| `PAGE` | Elimina pagina (disabilitata per `INIT`) | `lambda -> self.delete_page(page_id, page_name)` |
| `SHEET` | Elimina pagina (disabilitata per `INIT`) | `lambda -> self.delete_page(page_id, page_name)` |

Altre aree con context menu in `ide/`: **non presenti**.

## 1.4 Eventi UI “comando implicito”

| Evento | Dove | Effetto |
|---|---|---|
| `tree.itemClicked` | `MainWindow.on_tree_clicked` | Se PAGE: apre tab pagina + sheetbar su foglio 0. Se SHEET: apre pagina e seleziona foglio indicato. |
| `sheetbar.currentChanged` | `MainWindow.on_sheetbar_changed` | Cambia foglio nel `PageEditorTab` via metodi fallback (`set_sheet_index`, `select_sheet`, `open_sheet`, `show_sheet`, `set_current_sheet`). |
| `tabs.currentChanged` | `MainWindow.on_top_tab_changed` | Sincronizza sheetbar rispetto al file della tab corrente. |
| `tabs.tabCloseRequested` | `MainWindow.on_close_top_tab` | Chiusura tab editor con prompt salvataggio se dirty. |
| `diag.itemDoubleClicked` | `MainWindow.on_diag_double_clicked` | Jump da diagnostica a file/pagina/foglio e (se disponibile) `goto_line(line)`. |
| `timer.timeout` | `MainWindow.refresh_status` | Poll stato runtime periodico. |

## 1.5 Collegamenti importanti (navigazione)

### Click su diagnostica → jump file/riga

Catena implementativa:
1. Diagnostiche popolano item con metadata file+riga (`diag_set`, `UserRole`, `UserRole+1`).
2. `on_diag_double_clicked` legge metadata, mappa `rel path -> (page_id, page_name, sheet_idx0)` con `_infer_page_from_file_path`.
3. Apre tab pagina (`_open_page_tab`), seleziona foglio (`set_current_sheet`), sincronizza sheetbar e selezione tree.
4. Se disponibile `goto_line`, esegue salto alla riga.

Colonna: non è gestita (solo riga). **Colonna = DA VERIFICARE / non implementata nel jump attuale**.

---

## 2) Dialog e widget ausiliari (`ide/dialogs.py`)

## 2.1 `ProjectPickerDialog`

| Comando implicito/esplicito | Handler | Effetto |
|---|---|---|
| Pulsante `...` | `browse` | Selezione cartella base progetti |
| Pulsante `Aggiorna` | `refresh` | Ricarica lista progetti |
| Doppio click lista | `on_double` | Seleziona progetto e `accept()` dialog |
| `Close` (`QDialogButtonBox`) | `reject` | Chiusura dialog |

## 2.2 `NewProjectDialog`

| Comando | Handler | Effetto |
|---|---|---|
| Pulsante `...` | `pick_base` | Sceglie cartella base |
| `OK/Cancel` | `accept` / `reject` | Conferma o annulla creazione |

## 2.3 `AddPageDialog`

| Comando | Handler | Effetto |
|---|---|---|
| `OK/Cancel` | `accept` / `reject` | Conferma/annulla aggiunta pagina |

## 2.4 `SettingsWidget` (tab Settings)

| Comando UI | Handler | Effetto |
|---|---|---|
| Nuovo | `new_profile` | Prepara nuovo profilo |
| Salva | `save_current` | Crea/aggiorna profilo runtime |
| Rinomina | `rename_current` | Workflow rinomina in due fasi |
| Cancella | `delete_selected` | Elimina profilo selezionato |
| Cambio combo profilo | `on_combo_changed` | Attiva profilo selezionato e propaga segnale |

Context menu dedicati: **non presenti**.

---

## 3) Runtime UI (`runtime/localsim/knetx_sim_control.py`)

Finestra standalone `SimControlWindow` (no menubar/toolbar/context menu).

| Pulsante/azione | Handler | Effetto |
|---|---|---|
| Start Sim | `on_start_sim` | Avvia processo LocalSim se offline |
| Shutdown Sim | `on_shutdown_sim` | Spegne runtime via comando `SHUTDOWN` (fallback terminate) |
| RUN | `on_run` | Invio comando `START` |
| STOP | `on_stop` | Invio comando `STOP` |
| Apri log | `on_open_log` | Apre file log locale |
| Chiusura finestra | `closeEvent` | Tenta shutdown runtime se online |

Evento implicito:
- `timer.timeout -> refresh` ogni 1000 ms per stato online/uptime e enabled-state pulsanti.

---

## 4) Tool UI (`tools/knetx_new_project.py`)

> Questo file contiene una UI “legacy/demo” parallela all’IDE principale.

## 4.1 Menu bar

### `&File`

| Comando UI | Handler | Shortcut |
|---|---|---|
| Nuovo progetto... | `new_project` | — |
| Apri progetto... | `open_project` | — |
| Chiudi progetto | `close_project` | — |
| Salva | `save_current` | `Ctrl+S` |
| Salva tutto | `save_all` | — |
| Salva progetto con nome... | `save_project_as` | — |
| Elimina progetto... | `delete_project` | — |
| Esci | `close` | — |

### `&Progetto`

| Comando UI | Handler | Shortcut |
|---|---|---|
| Aggiungi pagina... | `add_page` | — |

## 4.2 Toolbar

| Azione | Handler | Tooltip/testo |
|---|---|---|
| Nuovo progetto | `new_project` | tooltip esplicito assente |
| Apri progetto | `open_project` | tooltip esplicito assente |
| Chiudi progetto | `close_project` | tooltip esplicito assente |
| Aggiungi pagina | `add_page` | tooltip esplicito assente |
| Salva | `save_current` | tooltip esplicito assente |
| Salva tutto | `save_all` | tooltip esplicito assente |
| Settings | `tabs.setCurrentWidget(tab_settings)` | tooltip esplicito assente |
| Connetti | `refresh_status` | tooltip esplicito assente |
| Compila | `stub_compile` | tooltip esplicito assente |
| Download | `stub_download` | tooltip esplicito assente |

## 4.3 Context menu

Area: albero progetto (`on_tree_context_menu`).

| Nodo | Voci | Handler |
|---|---|---|
| `PAGES_ROOT` | Nuova pagina | `add_page` |
| `PAGE` | Elimina pagina (disabilitata per `INIT`) | `lambda -> delete_page(page_id, page_name)` |

## 4.4 Eventi impliciti

| Evento | Handler | Effetto |
|---|---|---|
| `tree.itemClicked` | `on_tree_clicked` | PAGE/SHEET aprono pagina+foglio |
| `sheetbar.currentChanged` | `on_sheetbar_changed` | Cambio foglio |
| `tabs.tabCloseRequested` | `on_close_tab` | Chiusura tab con prompt save |
| `tabs.currentChanged` | `on_top_tab_changed` | Sync sheetbar |
| `timer.timeout` | `refresh_status` | Ping runtime periodico |

---

## 5) Gap / DA VERIFICARE

- Shortcut oltre `Ctrl+S`: non risultano binding espliciti nel codice attuale.
- Tooltip custom per toolbar/menu: non impostati esplicitamente.
- Jump diagnostica: supporta file+riga; colonna non gestita.
- Context menu su output/diagnostica/editor/tabelle variabili: non implementati al momento.
