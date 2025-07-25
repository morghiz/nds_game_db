__version__ = "1.0"
import sys, os, struct, shutil
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog, QMessageBox, QGroupBox, QGridLayout, QComboBox, QListWidget, QListWidgetItem, QSplitter, QTabWidget, QDialog, QDialogButtonBox
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PIL import Image
from io import BytesIO
import re
import uuid
import zipfile
import tempfile
import requests # Importa requests per le richieste HTTP

DS_SCREEN_WIDTH = 256
DS_SCREEN_HEIGHT = 192
LIST_ICON_SIZE = 48

def pil_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    byte_array = BytesIO()
    pil_image.save(byte_array, format='PNG')
    byte_array.seek(0)
    pixmap = QPixmap()
    pixmap.loadFromData(byte_array.getvalue())
    return pixmap

def sanitize_filename(text: str) -> str:
    s = text.replace(" ", "_")
    s = re.sub(r'[^\w.-]', '', s)
    s = s[:100]
    return s.lower()

@dataclass
class NDSInfo:
    title: str
    icon: Optional[bytes]
    filename: str
    filesize: int
    game_id: str = ""
    creator: str = ""
    version: str = ""

class NDSExtractor:
    @staticmethod
    def extract_info(filepath: str) -> NDSInfo:
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        with open(filepath, 'rb') as f:
            header = f.read(0x200)
            title_bytes = header[0x00:0x0C]
            title = title_bytes.decode('ascii', errors='ignore').strip('\x00')
            if not title:
                title = os.path.splitext(filename)[0]
            
            game_id_bytes = header[0x0C:0x10]
            game_id = game_id_bytes.decode('ascii', errors='ignore').strip('\x00')

            return NDSInfo(title=title, icon=None, filename=filename, filesize=filesize, game_id=game_id)

class DatabaseEntry:
    def __init__(self, line: str = ""):
        self.name = ""
        self.platform = "nds"
        self.region = "ANY"
        self.version = ""
        self.creator = ""
        self.download_url = ""
        self.filename = ""
        self.filesize = "0"
        self.icon_url = ""
        self.internal_file_id = ""
        self.game_id = ""

        if line.strip():
            parts = line.strip().split('\t')
            self.name = parts[0] if len(parts) > 0 else ""
            self.platform = parts[1] if len(parts) > 1 else "nds"
            self.region = parts[2] if len(parts) > 2 else "ANY"
            self.version = parts[3] if len(parts) > 3 else ""
            self.creator = parts[4] if len(parts) > 4 else ""
            self.download_url = parts[5] if len(parts) > 5 else ""
            self.filename = parts[6] if len(parts) > 6 else ""
            self.filesize = parts[7] if len(parts) > 7 else "0"
            self.icon_url = parts[8] if len(parts) > 8 else ""
            self.game_id = parts[9] if len(parts) > 9 else ""
        
        self.internal_file_id = sanitize_filename(f"{self.name}_{self.version}_{self.region}") if self.name else str(uuid.uuid4())

    def to_line(self) -> str:
        return f"{self.name}\t{self.platform}\t{self.region}\t{self.version}\t{self.creator}\t{self.download_url}\t{self.filename}\t{self.filesize}\t{self.icon_url}\t{self.game_id}"

    def to_line_relative(self) -> str:
        relative_download = self.download_url.split('/')[-1] if self.download_url and not self.download_url.startswith('http') else self.download_url
        relative_icon = self.icon_url.split('/')[-1] if self.icon_url and not self.icon_url.startswith('http') else self.icon_url
        return f"{self.name}\t{self.platform}\t{self.region}\t{self.version}\t{self.creator}\t{relative_download}\t{self.filename}\t{self.filesize}\t{relative_icon}\t{self.game_id}"

class EditDialog(QDialog):
    def __init__(self, entry: DatabaseEntry, base_url: str, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.base_url = base_url
        self.cover_path = None # Può essere un URL remoto o un percorso locale
        self.init_ui()
        self.load_entry_data()
    def init_ui(self):
        self.setWindowTitle("Modifica Entry")
        self.setFixedSize(500, 450)
        layout = QVBoxLayout(self)
        cover_group = QGroupBox("Copertina")
        cover_layout = QHBoxLayout(cover_group)
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText("Nessuna Copertina")
        cover_layout.addWidget(self.cover_label)
        cover_buttons = QVBoxLayout()
        self.load_cover_btn = QPushButton("Carica Copertina Locale")
        self.load_cover_btn.clicked.connect(self.load_cover)
        cover_buttons.addWidget(self.load_cover_btn)
        self.search_gametdb_btn = QPushButton("Cerca GameTDB")
        self.search_gametdb_btn.clicked.connect(self.search_gametdb_cover_dialog)
        cover_buttons.addWidget(self.search_gametdb_btn)
        self.remove_cover_btn = QPushButton("Rimuovi Copertina")
        self.remove_cover_btn.clicked.connect(self.remove_cover)
        cover_buttons.addWidget(self.remove_cover_btn)
        cover_layout.addLayout(cover_buttons)
        layout.addWidget(cover_group)
        fields_group = QGroupBox("Informazioni")
        fields_layout = QGridLayout(fields_group)
        fields_layout.addWidget(QLabel("Nome:"), 0, 0)
        self.name_edit = QLineEdit()
        fields_layout.addWidget(self.name_edit, 0, 1)
        fields_layout.addWidget(QLabel("Versione:"), 1, 0)
        self.version_edit = QLineEdit()
        fields_layout.addWidget(self.version_edit, 1, 1)
        fields_layout.addWidget(QLabel("Creatore:"), 2, 0)
        self.creator_edit = QLineEdit()
        fields_layout.addWidget(self.creator_edit, 2, 1)
        fields_layout.addWidget(QLabel("Piattaforma:"), 3, 0)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["nds", "dsi"])
        fields_layout.addWidget(self.platform_combo, 3, 1)
        fields_layout.addWidget(QLabel("Regione:"), 4, 0)
        self.region_combo = QComboBox()
        self.region_combo.addItems(["ANY", "EUR", "USA", "JPN"])
        fields_layout.addWidget(self.region_combo, 4, 1)
        fields_layout.addWidget(QLabel("Game ID:"), 5, 0)
        self.game_id_edit = QLineEdit()
        self.game_id_edit.setReadOnly(True)
        fields_layout.addWidget(self.game_id_edit, 5, 1)
        layout.addWidget(fields_group)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_image_to_label(self, path_or_url: str):
        if path_or_url.startswith('http'):
            try:
                pixmap = QPixmap()
                if pixmap.load(path_or_url):
                    pixmap = pixmap.scaled(DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.cover_label.setPixmap(pixmap)
                    self.cover_path = path_or_url
                else:
                    self.cover_label.clear()
                    self.cover_label.setText("Errore caricamento remoto")
            except Exception as e:
                self.cover_label.clear()
                self.cover_label.setText(f"Errore caricamento remoto: {e}")
        elif Path(path_or_url).exists():
            try:
                pil_image = Image.open(path_or_url)
                pil_image.thumbnail((DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2), Image.LANCZOS)
                self.cover_label.setPixmap(pil_to_qpixmap(pil_image))
                self.cover_path = path_or_url
            except Exception as e:
                self.cover_label.clear()
                self.cover_label.setText(f"Errore caricamento locale: {e}")
        else:
            self.cover_label.clear()
            self.cover_label.setText("Nessuna Copertina")


    def load_entry_data(self):
        self.name_edit.setText(self.entry.name)
        self.version_edit.setText(self.entry.version)
        self.creator_edit.setText(self.entry.creator)
        platform_index = self.platform_combo.findText(self.entry.platform)
        if platform_index >= 0:
            self.platform_combo.setCurrentIndex(platform_index)
        region_index = self.region_combo.findText(self.entry.region)
        if region_index >= 0:
            self.region_combo.setCurrentIndex(region_index)
        self.game_id_edit.setText(self.entry.game_id)
        
        if self.entry.icon_url:
            self._load_image_to_label(self.entry.icon_url)
        else:
            self.cover_label.setText("Nessuna Copertina")

    def load_cover(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona Copertina Locale", "", "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)")
        if filepath:
            self._load_image_to_label(filepath)
    
    def search_gametdb_cover_dialog(self):
        game_id = self.game_id_edit.text().strip()
        if not game_id:
            QMessageBox.warning(self, "Errore", "Impossibile cercare su GameTDB: Game ID non disponibile.")
            return

        lang_order = ["EN", "US", "FR", "DE", "ES", "IT", "NL", "PT", "JA", "CH", "AU", "SE", "DK", "NO", "FI", "TR", "KO", "ZH", "RU", "MX", "CA"]
        found_url = None

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for lang in lang_order:
                url = f"https://art.gametdb.com/ds/coverS/{lang}/{game_id}.png"
                try:
                    response = requests.head(url, timeout=5)
                    if response.status_code == 200:
                        found_url = url
                        break
                except requests.exceptions.RequestException:
                    continue # Continua con la prossima lingua in caso di errore di rete
            
            if found_url:
                self._load_image_to_label(found_url)
                QMessageBox.information(self, "Successo", f"Copertina GameTDB trovata e caricata: {found_url}")
            else:
                QMessageBox.warning(self, "Non Trovata", "Nessuna copertina trovata su GameTDB per questo Game ID. Selezionane una manualmente.")
                self.remove_cover() # Pulisci la preview se non trovata
        finally:
            QApplication.restoreOverrideCursor()


    def remove_cover(self):
        self.cover_label.clear()
        self.cover_label.setText("Nessuna Copertina")
        self.cover_path = "" # Imposta a stringa vuota per indicare nessuna copertina

    def get_updated_entry(self) -> DatabaseEntry:
        self.entry.name = self.name_edit.text().strip()
        self.entry.version = self.version_edit.text().strip()
        self.entry.creator = self.creator_edit.text().strip()
        self.entry.platform = self.platform_combo.currentText()
        self.entry.region = self.region_combo.currentText()
        # Il game_id non viene modificato qui, poiché dovrebbe essere fisso dalla ROM
        self.entry.internal_file_id = sanitize_filename(f"{self.entry.name}_{self.entry.version}_{self.entry.region}")
        self.entry.icon_url = self.cover_path # Aggiorna l'URL della copertina
        return self.entry

class FileManager:
    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip('/')
        self.roms_dir = Path("assets/roms")
        self.covers_dir = Path("assets/covers") # Mantenuto per copertine caricate localmente
        self.roms_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
    
    def copy_rom_file(self, nds_path: str, file_identifier: str) -> tuple[str, str]:
        rom_ext = Path(nds_path).suffix
        nds_filename_on_disk = f"{file_identifier}{rom_ext}"
        nds_dest = self.roms_dir / nds_filename_on_disk
        
        shutil.copy2(nds_path, nds_dest)
        rom_url = f"{self.base_url}/assets/roms/{nds_filename_on_disk}" if self.base_url else f"assets/roms/{nds_filename_on_disk}"
        return rom_url, nds_filename_on_disk

    def copy_local_cover_file(self, cover_path: str, file_identifier: str) -> str:
        if not cover_path or not Path(cover_path).exists():
            return ""
        
        cover_filename_on_disk = f"{file_identifier}.png"
        cover_dest = self.covers_dir / cover_filename_on_disk
        try:
            pil_image = Image.open(cover_path)
            pil_image.thumbnail((DS_SCREEN_WIDTH, DS_SCREEN_HEIGHT), Image.LANCZOS)
            pil_image = pil_image.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
            pil_image.save(cover_dest, format='PNG')
            return f"{self.base_url}/assets/covers/{cover_filename_on_disk}" if self.base_url else f"assets/covers/{cover_filename_on_disk}"
        except Exception as e:
            print(f"Errore copiando e ridimensionando copertina locale: {e}")
            return ""

    def remove_local_cover_file(self, file_identifier: str):
        for cover_file in self.covers_dir.glob(f"{file_identifier}.*"):
            if cover_file.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                try:
                    cover_file.unlink()
                except OSError as e:
                    print(f"Errore eliminando copertina locale {cover_file}: {e}")

class NDSDatabaseManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.database_path = "database.txt"
        self.url_path = "url.txt"
        self.entries = []
        self.base_url = ""
        self.current_nds_path = None
        self.current_cover_path = None # Può essere un percorso locale o un URL remoto
        self.load_base_url()
        self.file_manager = FileManager(self.base_url)
        self.init_ui()
        self.load_database()
    def load_base_url(self):
        if os.path.exists(self.url_path):
            try:
                with open(self.url_path, 'r', encoding='utf-8') as f:
                    self.base_url = f.read().strip()
            except Exception as e:
                print(f"Errore caricando URL base: {e}")
                self.base_url = ""
    def init_ui(self):
        self.setWindowTitle("NDS Database Manager")
        self.setGeometry(100, 100, 1000, 700)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.tab_widget = QTabWidget()
        central_widget_layout = QVBoxLayout(central_widget)
        central_widget_layout.addWidget(self.tab_widget)
        self.add_tab = QWidget()
        self.tab_widget.addTab(self.add_tab, "Aggiungi ROM")
        self.init_add_tab()
        self.view_tab = QWidget()
        self.tab_widget.addTab(self.view_tab, "Gestisci ROM")
        self.init_view_tab()
        self.statusBar().showMessage("Pronto")
    def init_add_tab(self):
        layout = QVBoxLayout(self.add_tab)
        url_group = QGroupBox("Configurazione URL")
        url_layout = QHBoxLayout(url_group)
        url_layout.addWidget(QLabel("URL Base:"))
        self.base_url_edit = QLineEdit(self.base_url)
        self.base_url_edit.textChanged.connect(self.update_base_url)
        url_layout.addWidget(self.base_url_edit)
        layout.addWidget(url_group)
        file_group = QGroupBox("Carica File")
        file_layout = QGridLayout(file_group)
        file_layout.addWidget(QLabel("File NDS:"), 0, 0)
        self.nds_path_label = QLabel("Nessun file selezionato")
        file_layout.addWidget(self.nds_path_label, 0, 1)
        self.load_nds_button = QPushButton("Seleziona NDS")
        self.load_nds_button.clicked.connect(self.load_nds_file)
        file_layout.addWidget(self.load_nds_button, 0, 2)
        file_layout.addWidget(QLabel("Copertina:"), 1, 0)
        self.cover_path_label = QLabel("Nessuna copertina")
        file_layout.addWidget(self.cover_path_label, 1, 1)
        
        cover_buttons_layout = QHBoxLayout()
        self.load_cover_button = QPushButton("Seleziona Locale")
        self.load_cover_button.clicked.connect(self.load_cover_file)
        cover_buttons_layout.addWidget(self.load_cover_button)

        self.search_gametdb_button = QPushButton("Cerca GameTDB")
        self.search_gametdb_button.clicked.connect(self.search_gametdb_cover)
        cover_buttons_layout.addWidget(self.search_gametdb_button)
        file_layout.addLayout(cover_buttons_layout, 1, 2)
        
        layout.addWidget(file_group)
        preview_group = QGroupBox("Anteprima Copertina")
        preview_layout = QHBoxLayout(preview_group)
        self.cover_preview = QLabel()
        self.cover_preview.setFixedSize(DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2)
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setText("Nessuna Copertina")
        preview_layout.addWidget(self.cover_preview)
        layout.addWidget(preview_group)
        info_group = QGroupBox("Informazioni ROM")
        info_layout = QGridLayout(info_group)
        info_layout.addWidget(QLabel("Nome:"), 0, 0)
        self.name_edit = QLineEdit()
        info_layout.addWidget(self.name_edit, 0, 1)
        info_layout.addWidget(QLabel("Versione:"), 1, 0)
        self.version_edit = QLineEdit()
        info_layout.addWidget(self.version_edit, 1, 1)
        info_layout.addWidget(QLabel("Creatore:"), 2, 0)
        self.creator_edit = QLineEdit()
        info_layout.addWidget(self.creator_edit, 2, 1)
        info_layout.addWidget(QLabel("Piattaforma:"), 3, 0)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["nds", "dsi"])
        info_layout.addWidget(self.platform_combo, 3, 1)
        info_layout.addWidget(QLabel("Regione:"), 4, 0)
        self.region_combo = QComboBox()
        self.region_combo.addItems(["ANY", "EUR", "USA", "JPN"])
        info_layout.addWidget(self.region_combo, 4, 1)
        info_layout.addWidget(QLabel("Game ID:"), 5, 0)
        self.game_id_edit = QLineEdit()
        self.game_id_edit.setReadOnly(True)
        info_layout.addWidget(self.game_id_edit, 5, 1)
        layout.addWidget(info_group)
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Aggiungi al Database")
        self.add_button.clicked.connect(self.add_to_database)
        self.add_button.setEnabled(False)
        button_layout.addWidget(self.add_button)
        self.clear_button = QPushButton("Pulisci Campi")
        self.clear_button.clicked.connect(self.clear_fields)
        button_layout.addWidget(self.clear_button)
        layout.addLayout(button_layout)
    def init_view_tab(self):
        layout = QHBoxLayout(self.view_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.addWidget(QLabel("ROM nel Database:"))
        self.rom_list = QListWidget()
        self.rom_list.itemClicked.connect(self.on_rom_selected)
        list_layout.addWidget(self.rom_list)
        list_buttons = QHBoxLayout()
        self.edit_button = QPushButton("Modifica")
        self.edit_button.clicked.connect(self.edit_selected_rom)
        self.edit_button.setEnabled(False)
        list_buttons.addWidget(self.edit_button)
        self.delete_button = QPushButton("Elimina")
        self.delete_button.clicked.connect(self.delete_selected_rom)
        self.delete_button.setEnabled(False)
        list_buttons.addWidget(self.delete_button)
        list_layout.addLayout(list_buttons)
        splitter.addWidget(list_widget)
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.addWidget(QLabel("Dettagli ROM:"))
        self.details_cover = QLabel()
        self.details_cover.setFixedSize(DS_SCREEN_WIDTH, DS_SCREEN_HEIGHT)
        self.details_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
        details_layout.addWidget(self.details_cover)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        details_layout.addWidget(self.details_text)
        splitter.addWidget(details_widget)
        splitter.setSizes([400, 400])
        global_buttons = QHBoxLayout()
        self.save_database_button = QPushButton("Salva Database")
        self.save_database_button.clicked.connect(self.save_database)
        global_buttons.addWidget(self.save_database_button)
        self.refresh_button = QPushButton("Aggiorna Lista")
        self.refresh_button.clicked.connect(self.refresh_rom_list)
        global_buttons.addWidget(self.refresh_button)
        layout.addLayout(global_buttons)
    def update_base_url(self):
        self.base_url = self.base_url_edit.text().strip()
        self.file_manager = FileManager(self.base_url)
        try:
            with open(self.url_path, 'w', encoding='utf-8') as f:
                f.write(self.base_url)
        except Exception as e:
            print(f"Errore salvando URL base: {e}")

    def _load_cover_preview(self, path_or_url: str):
        if path_or_url.startswith('http'):
            try:
                pixmap = QPixmap()
                if pixmap.load(path_or_url):
                    pixmap = pixmap.scaled(DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.cover_preview.setPixmap(pixmap)
                    self.cover_path_label.setText(path_or_url)
                    self.statusBar().showMessage(f"Copertina remota caricata: {path_or_url}")
                else:
                    self.cover_preview.clear()
                    self.cover_preview.setText("Errore caricamento remoto")
                    self.cover_path_label.setText("Errore caricamento copertina remota")
                    self.statusBar().showMessage("Errore caricamento copertina remota.")
            except Exception as e:
                self.cover_preview.clear()
                self.cover_preview.setText(f"Errore: {e}")
                self.cover_path_label.setText("Errore caricamento copertina remota")
                self.statusBar().showMessage(f"Errore caricamento copertina remota: {e}")
        elif Path(path_or_url).exists():
            try:
                pil_image = Image.open(path_or_url)
                pil_image.thumbnail((DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2), Image.LANCZOS)
                self.cover_preview.setPixmap(pil_to_qpixmap(pil_image))
                self.cover_path_label.setText(os.path.basename(path_or_url))
                self.statusBar().showMessage(f"Copertina locale caricata: {os.path.basename(path_or_url)}")
            except Exception as e:
                self.cover_preview.clear()
                self.cover_preview.setText(f"Errore: {e}")
                self.cover_path_label.setText("Errore caricamento copertina locale")
                self.statusBar().showMessage(f"Errore caricamento copertina locale: {e}")
        else:
            self.cover_preview.clear()
            self.cover_preview.setText("Nessuna Copertina")
            self.cover_path_label.setText("Nessuna copertina selezionata")
            self.statusBar().showMessage("Nessuna copertina selezionata.")


    def load_nds_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona File NDS", "", "File NDS (*.nds *.dsi *.zip);;Tutti i file (*)")
        if filepath:
            original_filename = os.path.basename(filepath)
            self.current_nds_path = None
            extracted_rom_path = None

            if filepath.lower().endswith('.zip'):
                temp_dir = None
                try:
                    temp_dir = Path(tempfile.mkdtemp())
                    with zipfile.ZipFile(filepath, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    
                    largest_rom_path = None
                    largest_rom_size = -1

                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            if file.lower().endswith(('.nds', '.dsi')):
                                current_file_path = Path(root) / file
                                current_file_size = os.path.getsize(current_file_path)
                                if current_file_size > largest_rom_size:
                                    largest_rom_size = current_file_size
                                    largest_rom_path = current_file_path
                    
                    if largest_rom_path:
                        extracted_rom_path = str(largest_rom_path)
                        self.nds_path_label.setText(f"{original_filename} (estratto: {largest_rom_path.name})")
                    else:
                        QMessageBox.warning(self, "Errore", "Nessun file .nds o .dsi trovato nell'archivio ZIP.")
                        self.add_button.setEnabled(False)
                        return
                except Exception as e:
                    QMessageBox.critical(self, "Errore", f"Errore durante l'estrazione o la gestione del file ZIP: {e}")
                    self.add_button.setEnabled(False)
                    return
                finally:
                    # Non rimuovere temp_dir qui, la ROM estratta deve persistere per l'aggiunta
                    self.temp_zip_extraction_dir = temp_dir # Salva il riferimento per eliminarlo dopo
            else:
                extracted_rom_path = filepath
                self.nds_path_label.setText(original_filename)

            self.current_nds_path = extracted_rom_path
            try:
                nds_info = NDSExtractor.extract_info(self.current_nds_path)
                self.name_edit.setText(nds_info.title)
                self.game_id_edit.setText(nds_info.game_id)
                self.add_button.setEnabled(True)
                self.statusBar().showMessage(f"File NDS caricato: {nds_info.filename}")
                
                # Prova a cercare la copertina su GameTDB automaticamente
                self.current_cover_path = "" # Resetta la copertina corrente
                if nds_info.game_id:
                    self.search_gametdb_cover(auto_search=True)
                else:
                    QMessageBox.information(self, "Info", "Game ID non trovato nella ROM. Non è possibile cercare automaticamente la copertina su GameTDB.")

            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore leggendo il file NDS: {e}")
                self.add_button.setEnabled(False)
        else:
            self.add_button.setEnabled(False)

    def load_cover_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona Copertina Locale", "", "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)")
        if filepath:
            self.current_cover_path = filepath
            self._load_cover_preview(self.current_cover_path)

    def search_gametdb_cover(self, auto_search=False):
        game_id = self.game_id_edit.text().strip()
        if not game_id:
            if not auto_search:
                QMessageBox.warning(self, "Errore", "Impossibile cercare su GameTDB: Game ID non disponibile.")
            return

        lang_order = ["EN", "US", "FR", "DE", "ES", "IT", "NL", "PT", "JA", "CH", "AU", "SE", "DK", "NO", "FI", "TR", "KO", "ZH", "RU", "MX", "CA"]
        found_url = None

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for lang in lang_order:
                url = f"https://art.gametdb.com/ds/coverS/{lang}/{game_id}.png"
                try:
                    response = requests.head(url, timeout=5)
                    if response.status_code == 200:
                        found_url = url
                        break
                except requests.exceptions.RequestException:
                    continue
            
            if found_url:
                self.current_cover_path = found_url
                self._load_cover_preview(self.current_cover_path)
                if not auto_search:
                    QMessageBox.information(self, "Successo", f"Copertina GameTDB trovata e caricata: {found_url}")
            else:
                self.current_cover_path = "" # Nessuna copertina GameTDB trovata
                self._load_cover_preview(self.current_cover_path) # Pulisce la preview
                if not auto_search:
                    QMessageBox.warning(self, "Non Trovata", "Nessuna copertina trovata su GameTDB per questo Game ID. Selezionane una manualmente.")
        finally:
            QApplication.restoreOverrideCursor()

    def add_to_database(self):
        if not self.current_nds_path:
            QMessageBox.warning(self, "Errore", "Seleziona prima un file NDS!")
            return
        
        if not self.current_cover_path:
            reply = QMessageBox.question(self, "Nessuna Copertina",
                                        "Nessuna copertina automatica trovata e non ne hai selezionata una manualmente.\nVuoi continuare senza copertina o vuoi selezionarne una ora?",
                                        QMessageBox.StandardButton.Open | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Open:
                self.load_cover_file()
                if not self.current_cover_path: # Se l'utente non seleziona nulla dopo il prompt
                    return
            elif reply == QMessageBox.StandardButton.No:
                pass # Continua senza copertina
            
        try:
            temp_entry = DatabaseEntry()
            temp_entry.name = self.name_edit.text().strip() or "ROM Senza Nome"
            temp_entry.version = self.version_edit.text().strip()
            temp_entry.region = self.region_combo.currentText()
            temp_entry.internal_file_id = sanitize_filename(f"{temp_entry.name}_{temp_entry.version}_{temp_entry.region}")

            rom_url, actual_rom_filename_on_disk = self.file_manager.copy_rom_file(
                self.current_nds_path, temp_entry.internal_file_id
            )

            cover_url_to_save = ""
            if self.current_cover_path:
                if self.current_cover_path.startswith('http'):
                    cover_url_to_save = self.current_cover_path
                else: # È un percorso locale, copialo
                    cover_url_to_save = self.file_manager.copy_local_cover_file(
                        self.current_cover_path, temp_entry.internal_file_id
                    )
            
            entry = DatabaseEntry()
            entry.name = temp_entry.name
            entry.version = temp_entry.version
            entry.creator = self.creator_edit.text().strip()
            entry.platform = self.platform_combo.currentText()
            entry.region = temp_entry.region
            entry.download_url = rom_url
            entry.icon_url = cover_url_to_save
            entry.filename = actual_rom_filename_on_disk
            entry.filesize = str(os.path.getsize(self.current_nds_path))
            entry.internal_file_id = temp_entry.internal_file_id
            entry.game_id = self.game_id_edit.text().strip()

            self.entries.append(entry)
            self.clear_fields()
            self.refresh_rom_list()
            self.save_database()
            self.statusBar().showMessage(f"ROM '{entry.name}' aggiunta al database")
            QMessageBox.information(self, "Successo", f"ROM '{entry.name}' aggiunta con successo!")
            
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore aggiungendo la ROM: {e}")
        finally:
            if hasattr(self, 'temp_zip_extraction_dir') and self.temp_zip_extraction_dir.exists():
                shutil.rmtree(self.temp_zip_extraction_dir)
                del self.temp_zip_extraction_dir
    
    def clear_fields(self):
        self.current_nds_path = None
        self.current_cover_path = None
        
        self.nds_path_label.setText("Nessun file selezionato")
        self.cover_path_label.setText("Nessuna copertina")
        self.cover_preview.clear()
        self.cover_preview.setText("Nessuna Copertina")
        
        self.name_edit.clear()
        self.version_edit.clear()
        self.creator_edit.clear()
        self.platform_combo.setCurrentIndex(0)
        self.region_combo.setCurrentIndex(0)
        self.game_id_edit.clear()
        
        self.add_button.setEnabled(False)
    
    def refresh_rom_list(self):
        self.rom_list.clear()
        self.rom_list.setIconSize(QSize(LIST_ICON_SIZE, LIST_ICON_SIZE))
        for entry in self.entries:
            item = QListWidgetItem(f"{entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, entry)

            if entry.icon_url:
                pixmap = QPixmap()
                if entry.icon_url.startswith('http'):
                    if pixmap.load(entry.icon_url):
                        pixmap = pixmap.scaled(LIST_ICON_SIZE, LIST_ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        item.setIcon(QIcon(pixmap))
                else: # Percorso locale
                    cover_file = Path(entry.icon_url)
                    if cover_file.exists():
                        try:
                            pil_image = Image.open(str(cover_file))
                            pil_image.thumbnail((LIST_ICON_SIZE, LIST_ICON_SIZE), Image.LANCZOS)
                            pixmap = pil_to_qpixmap(pil_image)
                            item.setIcon(QIcon(pixmap))
                        except Exception as e:
                            print(f"Errore caricando icona per lista (locale) {cover_file}: {e}")
            self.rom_list.addItem(item)
    
    def on_rom_selected(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry:
            self.show_rom_details(entry)
            self.edit_button.setEnabled(True)
            self.delete_button.setEnabled(True)
    
    def show_rom_details(self, entry: DatabaseEntry):
        self.details_cover.clear()
        self.details_cover.setText("Caricamento...")

        if entry.icon_url:
            pixmap = QPixmap()
            if entry.icon_url.startswith('http'):
                if pixmap.load(entry.icon_url):
                    pixmap = pixmap.scaled(DS_SCREEN_WIDTH, DS_SCREEN_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.details_cover.setPixmap(pixmap)
                else:
                    self.details_cover.setText("Errore caricamento remoto")
            else: # Percorso locale
                cover_file = Path(entry.icon_url)
                if cover_file.exists():
                    try:
                        pil_image = Image.open(str(cover_file))
                        pil_image.thumbnail((DS_SCREEN_WIDTH, DS_SCREEN_HEIGHT), Image.LANCZOS)
                        self.details_cover.setPixmap(pil_to_qpixmap(pil_image))
                    except Exception as e:
                        self.details_cover.setText(f"Errore caricamento locale: {e}")
                else:
                    self.details_cover.setText("File copertina locale non trovato")
        else:
            self.details_cover.setText("Nessuna Copertina")
        
        details_text = f"""Nome: {entry.name}
Piattaforma: {entry.platform}
Regione: {entry.region}
Versione (interna): {entry.version}
Creatore (interna): {entry.creator}
Game ID: {entry.game_id}
Filename ROM (originale): {entry.filename}
Dimensione ROM: {entry.filesize} bytes
URL Download ROM: {entry.download_url}
URL Copertina: {entry.icon_url if entry.icon_url else 'N/A'}
ID Interno (per file): {entry.internal_file_id}"""
        
        self.details_text.setPlainText(details_text)
    
    def edit_selected_rom(self):
        current_item = self.rom_list.currentItem()
        if not current_item:
            return
        
        entry = current_item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        
        dialog = EditDialog(entry, self.base_url, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_entry = dialog.get_updated_entry()
            
            # Se la copertina è cambiata
            if updated_entry.icon_url != entry.icon_url:
                # Se la nuova icon_url è un percorso locale, copiala
                if updated_entry.icon_url and not updated_entry.icon_url.startswith('http'):
                    # Pulisci eventuali vecchie copertine locali associate a questo ID
                    self.file_manager.remove_local_cover_file(updated_entry.internal_file_id)
                    new_local_url = self.file_manager.copy_local_cover_file(updated_entry.icon_url, updated_entry.internal_file_id)
                    updated_entry.icon_url = new_local_url
                elif not updated_entry.icon_url: # Se la copertina è stata rimossa
                    self.file_manager.remove_local_cover_file(updated_entry.internal_file_id) # Rimuovi eventuali locali

            current_item.setText(f"{updated_entry.name}")
            self.show_rom_details(updated_entry)
            self.save_database()
            self.statusBar().showMessage(f"ROM '{updated_entry.name}' modificata")
    
    def delete_selected_rom(self):
        current_item = self.rom_list.currentItem()
        if not current_item:
            return
        
        entry = current_item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        
        reply = QMessageBox.question(
            self, "Conferma Eliminazione",
            f"Sei sicuro di voler eliminare '{entry.name}'?\n\n"
            "Questo rimuoverà l'entry dal database ma NON eliminerà i file ROM e copertina fisici.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.entries.remove(entry)
            self.refresh_rom_list()
            
            self.details_cover.clear()
            self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
            self.details_text.clear()
            
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            
            self.save_database()
            self.statusBar().showMessage(f"ROM '{entry.name}' eliminata dal database")
    
    def load_database(self):
        if os.path.exists(self.database_path):
            try:
                with open(self.database_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                self.entries = []
                if not lines:
                    self.statusBar().showMessage(f"Database '{self.database_path}' è vuoto.")
                    return

                db_version_line = lines[0].strip()
                if db_version_line == "1":
                    if len(lines) > 2:
                        for line in lines[2:]:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                parts = line.split('\t')
                                if len(parts) == 9:
                                    new_line = line + "\t"
                                    self.entries.append(DatabaseEntry(new_line))
                                elif len(parts) == 10:
                                    self.entries.append(DatabaseEntry(line))
                                else:
                                    print(f"Warning: Line with unexpected number of fields: {len(parts)} -> {line}")
                else:
                    QMessageBox.warning(self, "Attenzione", f"Versione database non riconosciuta: {db_version_line}. Potrebbero esserci problemi di compatibilità. Il database verrà inizializzato.")
                    self.entries = []


                self.refresh_rom_list()
                self.statusBar().showMessage(f"Database caricato: {len(self.entries)} entries")
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore caricando il database: {e}")
        else:
            try:
                with open(self.database_path, 'w', encoding='utf-8') as f:
                    f.write("1\n")
                    f.write("\t\n")
                self.statusBar().showMessage(f"Database '{self.database_path}' creato.")
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore creando il database: {e}")
    
    def save_database(self):
        try:
            with open(self.database_path, 'w', encoding='utf-8') as f:
                f.write("1\n")
                f.write("\t\n")
                for entry in self.entries:
                    f.write(entry.to_line() + '\n')
            
            relative_path = self.database_path.replace('.txt', '_relative.txt')
            with open(relative_path, 'w', encoding='utf-8') as f:
                f.write("1\n")
                f.write("\t\n")
                for entry in self.entries:
                    f.write(entry.to_line_relative() + '\n')
            
            self.statusBar().showMessage("Database salvato (completo e relativo)")
            QMessageBox.information(
                self, "Successo", 
                f"Database salvato con successo!\n\n"
                f"- Versione completa: {self.database_path}\n"
                f"- Versione relativa: {relative_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore salvando il database: {e}")

def main():
    app = QApplication(sys.argv)
    window = NDSDatabaseManager()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()