# LOCKLIST_OK

Documento di blocco modifiche UI/UX.

## Regole generali (vincolanti)

1. Ogni task futuro deve dichiarare **esplicitamente** quali parti di questa LOCKLIST **non** vengono toccate.
2. Se una modifica impatta una voce lockata, va approvata prima e documentata con diff mirato.
3. Dove il codice non espone un valore univoco, la voce resta marcata **DA VERIFICARE** (vietato inventare).

---

## UI BASELINE (NON TOCCARE)

## 1) Font editor ST

Baseline:
- Famiglia font codice: `Verdana`.
- Dimensione font codice: `8 pt`.
- Gap area numeri riga: `LINE_NUMBER_GAP_CM = 0.5`.

Punti di definizione/aggancio:
- Costanti in `ide/config.py`: `CODE_FONT_FAMILY`, `CODE_FONT_SIZE_PT`, `LINE_NUMBER_GAP_CM`.
- Applicazione in `ide/editor_st.py` (`StEditor.__init__`):
  - `self.setFont(f)`
  - `self.document().setDefaultFont(f)`
  - `self._ln_area.setFont(self.font())`

**NON TOCCARE**: famiglia, pointSize, applicazione simultanea su editor+documento+line numbers.

## 2) Syntax highlighting

Baseline rilevata:
- Nell’editor ST attuale (`StEditor`) **non** è agganciata alcuna classe `QSyntaxHighlighter` custom.
- Evidenziazione presente solo per riga corrente (`highlightCurrentLine`, sfondo chiaro).

**NON TOCCARE**:
- comportamento della current-line highlight senza ticket dedicato.

**DA VERIFICARE**:
- eventuali highlighter esterni/plugin non presenti nel repository corrente.

## 3) Dimensioni / geometry / layout persistente

Baseline:
- Splitter principale IDE: `self.split.setSizes([260, 900])`.
- Splitter output/diagnostica IDE: `out_split.setSizes([220, 120])`.
- Sheetbar bottom: altezza fissa `28` px (`setFixedHeight(28)`).
- Sim Control: `setFixedHeight(110)` e `resize(520, 110)`.

Persistenza `QSettings` rilevata:
- Chiavi usate: `last_project_dir`, `last_base_dir`.
- Nessuna `saveGeometry/restoreGeometry/saveState/restoreState` per main window o dock.

**NON TOCCARE**:
- valori splitter baseline e altezza sheetbar.
- semantica attuale delle chiavi `QSettings` sopra.

**DA VERIFICARE**:
- persistenza geometria finestra principale (oggi non implementata).

## 4) Tabelle / viste tabellari

Baseline rilevata:
- Non ci sono `QTableWidget/QTableView` operative nell’IDE principale.
- Diagnostica usa `QTreeWidget` con colonne: `Sev | File | Line | Msg`.
- Resize automatico solo per colonne 0 e 2 (`resizeColumnToContents`).

Selection/Edit behavior:
- `setSelectionBehavior` e `setEditTriggers` non sono configurati esplicitamente nelle viste correnti.

**NON TOCCARE**:
- ordine colonne diagnostica (`Sev, File, Line, Msg`).
- assenza di editing inline su diagnostica (comportamento implicito corrente).

**DA VERIFICARE**:
- larghezze fisse finali colonna 1/3 (non bloccate da codice).

## 5) Finestre/dialog “ad hoc” esistenti

### IDE principale
- `ProjectPickerDialog` (apri progetto) → aperto da `MainWindow.open_project`.
- `NewProjectDialog` (nuovo progetto) → aperto da `MainWindow.new_project`.
- `AddPageDialog` (aggiungi pagina) → aperto da `MainWindow.add_page`.
- `SettingsWidget` (tab incorporata, non dialog esterno) → accesso via toolbar `Settings`.
- Tab `Output` con diagnostica incorporata.

### Runtime/tool UI
- `SimControlWindow` (`runtime/localsim/knetx_sim_control.py`) standalone.
- UI legacy `tools/knetx_new_project.py` con struttura simile ma separata.

**NON TOCCARE**:
- pattern di apertura corrente (azioni menu/toolbar → dialog specifico).
- comportamento toggle Connect/Disconnect in toolbar IDE.
- doppio click su diagnostica come trigger di navigazione.

## 6) Menù / toolbar / context menu (baseline comportamentale)

**NON TOCCARE** (senza change request esplicita):
- menu `File` e `Progetto` dell’IDE con la gerarchia attuale.
- shortcut `Ctrl+S` su comando `Salva`.
- context menu albero:
  - `PAGES_ROOT` → `Nuova pagina`
  - `PAGE/SHEET` → `Elimina pagina` (INIT disabilitato)
- assenza di context menu dedicati su output/editor/diagnostica (stato attuale).

## 7) Regola d’oro operativa

Per qualsiasi task futuro, includere nel piano:
- elenco esplicito delle voci locklist impattate;
- elenco delle voci locklist **garantite intatte**;
- eventuali punti **DA VERIFICARE** che restano fuori scope.

Se manca questa dichiarazione, il task è da considerarsi incompleto.
