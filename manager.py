__version__ = "1.0"
import sys, os, struct, shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, asdict, field
import json
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog, QMessageBox, QGroupBox, QGridLayout, QComboBox, QListWidget, QListWidgetItem, QSplitter, QTabWidget, QDialog, QDialogButtonBox
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PIL import Image
from io import BytesIO
import re
import uuid
import zipfile
import tempfile
import requests

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
    maker_code: str = ""
    rom_version: int = 0
    region_from_rom: str = "ANY"

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

            maker_code_bytes = header[0x12:0x14]
            maker_code = maker_code_bytes.decode('ascii', errors='ignore').strip('\x00')

            rom_version_byte = header[0x1E]
            rom_version = int(rom_version_byte)

            game_id_region_map = {
                'A': "ANY", 'B': "ANY", 'C': "CHI", 'D': "EUR", 'E': "USA", 
                'F': "EUR", 'G': "ANY", 'H': "EUR", 'I': "EUR", 'J': "JPN", 
                'K': "ANY", 'L': "USA", 'M': "EUR", 'N': "EUR", 'O': "ANY", 
                'P': "EUR", 'Q': "EUR", 'R': "RU", 'S': "ES", 'T': "USA", 
                'U': "AUS", 'V': "EUR", 'W': "EUR", 'X': "EUR", 'Y': "EUR", 'Z': "EUR",
            }

            region_from_game_id = "ANY"
            if len(game_id) >= 4:
                fourth_char = game_id[3].upper()
                region_from_game_id = game_id_region_map.get(fourth_char, "ANY")

            region_from_rom = region_from_game_id

            return NDSInfo(title=title, icon=None, filename=filename, filesize=filesize, 
                           game_id=game_id, maker_code=maker_code, rom_version=rom_version, 
                           region_from_rom=region_from_rom)

@dataclass
class RomVersion:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    region: str = "ANY"
    version: str = ""
    download_url: str = ""
    filename: str = ""
    filesize: str = "0"
    icon_url: str = ""
    game_id: str = ""
    extracted_region_from_rom: str = "ANY"
    internal_file_id: str = ""

    def __post_init__(self):
        if not self.internal_file_id:
            self.internal_file_id = sanitize_filename(f"{self.game_id}_{self.region}_{self.id[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(**data)

@dataclass
class GameEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    creator: str = ""
    platform: str = "nds"
    game_id: str = ""
    rom_versions: List[RomVersion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['rom_versions'] = [rv.to_dict() for rv in self.rom_versions]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        rom_versions_data = data.pop('rom_versions', [])
        game_entry = cls(**data)
        game_entry.rom_versions = [RomVersion.from_dict(rv_data) for rv_data in rom_versions_data]
        return game_entry

    def to_lines_for_txt(self) -> List[str]:
        lines = []
        for rv in self.rom_versions:
            title_with_region = self.name
            if rv.region and rv.region != "ANY":
                title_with_region += f" - {rv.region}"
            
            # Formato richiesto: titolo(con suffisso regionale) tab console tab regione tab versione tab creatore tab romurl tab filename+ext tab filesize tab coverurl
            line = (f"{title_with_region}\t{self.platform}\t{rv.region}\t{rv.version}\t{self.creator}\t"
                    f"{rv.download_url}\t{rv.filename}\t{rv.filesize}\t{rv.icon_url}")
            lines.append(line)
        return lines


class ImageLoader:
    def __init__(self, cover_label: QLabel, status_bar_method: Optional[Callable[[str], None]] = None):
        self.cover_label = cover_label
        self.status_bar_method = status_bar_method
        self.current_cover_path = ""

    def _update_status_bar(self, message: str):
        if self.status_bar_method:
            self.status_bar_method(message)

    def load_image_to_label(self, path_or_url: str):
        self.current_cover_path = ""
        if path_or_url.startswith('http'):
            try:
                pixmap = QPixmap()
                response = requests.get(path_or_url, timeout=5)
                response.raise_for_status()
                pixmap.loadFromData(response.content)

                if not pixmap.isNull():
                    pixmap = pixmap.scaled(DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.cover_label.setPixmap(pixmap)
                    self.current_cover_path = path_or_url
                    self._update_status_bar(f"Copertina remota caricata: {path_or_url}")
                else:
                    self.cover_label.clear()
                    self.cover_label.setText("Errore caricamento remoto")
                    self._update_status_bar("Errore caricamento copertina remota.")
            except requests.exceptions.Timeout:
                self.cover_label.clear()
                self.cover_label.setText("Timeout caricamento remoto")
                self._update_status_bar("Timeout caricamento copertina remota.")
            except requests.exceptions.RequestException as e:
                self.cover_label.clear()
                self.cover_label.setText(f"Errore: {e}")
                self._update_status_bar(f"Errore caricamento copertina remota: {e}")
            except Exception as e:
                self.cover_label.clear()
                self.cover_label.setText(f"Errore generico: {e}")
                self._update_status_bar(f"Errore generico caricamento copertina remota: {e}")
        elif Path(path_or_url).exists():
            try:
                pil_image = Image.open(path_or_url)
                pil_image.thumbnail((DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2), Image.LANCZOS)
                self.cover_label.setPixmap(pil_to_qpixmap(pil_image))
                self.current_cover_path = path_or_url
                self._update_status_bar(f"Copertina locale caricata: {os.path.basename(path_or_url)}")
            except Exception as e:
                self.cover_label.clear()
                self.cover_label.setText(f"Errore: {e}")
                self._update_status_bar(f"Errore caricamento copertina locale: {e}")
        else:
            self.cover_label.clear()
            self.cover_label.setText("Nessuna Copertina")
            self._update_status_bar("Nessuna copertina selezionata.")

    def search_gametdb_cover(self, game_id: str, auto_search: bool = False):
        if not game_id:
            if not auto_search:
                QMessageBox.warning(self.cover_label.parentWidget(), "Errore", "Impossibile cercare su GameTDB: Game ID non disponibile.")
            return

        game_id_to_gametdb_lang_map = {
                'A': "ANY", 'B': "ANY", 'C': "CHI", 'D': "EUR", 'E': "USA", 
                'F': "EUR", 'G': "ANY", 'H': "EUR", 'I': "EUR", 'J': "JPN", 
                'K': "ANY", 'L': "USA", 'M': "EUR", 'N': "EUR", 'O': "ANY", 
                'P': "EUR", 'Q': "DA", 'R': "RU", 'S': "ES", 'T': "USA", 
                'U': "AUS", 'V': "EUR", 'W': "EUR", 'X': "EUR", 'Y': "EUR", 'Z': "EUR"
            }

        primary_lang = "EN"
        if len(game_id) >= 4:
            fourth_char = game_id[3].upper()
            primary_lang = game_id_to_gametdb_lang_map.get(fourth_char, "EN")

        lang_order = [primary_lang]
        fallback_langs = ["EN", "US", "FR", "DE", "ES", "IT", "NL", "PT", "JA", "CH", " " , "AU", "SE", "DA", "NO", "FI", "TR", "KO", "ZH", "RU", "MX", "CA"]
        for lang in fallback_langs:
            if lang not in lang_order:
                lang_order.append(lang)
        
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
                self.load_image_to_label(found_url)
                if not auto_search:
                    QMessageBox.information(self.cover_label.parentWidget(), "Successo", f"Copertina GameTDB trovata e caricata: {found_url}")
            else:
                self.remove_cover()
                if not auto_search:
                    QMessageBox.warning(self.cover_label.parentWidget(), "Non Trovata", "Nessuna copertina trovata su GameTDB per questo Game ID. Selezionane una manualmente.")
        finally:
            QApplication.restoreOverrideCursor()

    def remove_cover(self):
        self.cover_label.clear()
        self.cover_label.setText("Nessuna Copertina")
        self.current_cover_path = ""

class EditDialog(QDialog):
    def __init__(self, rom_version: RomVersion, base_url: str, parent=None):
        super().__init__(parent)
        self.rom_version = rom_version
        self.base_url = base_url
        self.init_ui()
        self.image_loader = ImageLoader(self.cover_label)
        self.load_entry_data()

    def init_ui(self):
        self.setWindowTitle("Modifica Versione ROM")
        self.setFixedSize(500, 600)
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

        fields_group = QGroupBox("Informazioni ROM")
        fields_layout = QGridLayout(fields_group)
        
        row = 0
        fields_layout.addWidget(QLabel("Regione (Utente):"), row, 0)
        self.region_combo = QComboBox()
        self.region_combo.addItems(["ANY", "EUR", "USA", "JPN", "CHI", "AUS"])
        fields_layout.addWidget(self.region_combo, row, 1); row += 1

        fields_layout.addWidget(QLabel("Versione:"), row, 0)
        self.version_edit = QLineEdit()
        fields_layout.addWidget(self.version_edit, row, 1); row += 1

        fields_layout.addWidget(QLabel("Game ID:"), row, 0)
        self.game_id_edit = QLineEdit()
        self.game_id_edit.setReadOnly(True)
        fields_layout.addWidget(self.game_id_edit, row, 1); row += 1

        fields_layout.addWidget(QLabel("Regione (da ROM):"), row, 0)
        self.extracted_region_label = QLabel()
        fields_layout.addWidget(self.extracted_region_label, row, 1); row += 1

        layout.addWidget(fields_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def load_entry_data(self):
        self.version_edit.setText(self.rom_version.version)
        
        region_index = self.region_combo.findText(self.rom_version.region)
        if region_index >= 0:
            self.region_combo.setCurrentIndex(region_index)
        else:
            self.region_combo.setCurrentIndex(self.region_combo.findText("ANY"))
        
        self.game_id_edit.setText(self.rom_version.game_id)
        self.extracted_region_label.setText(self.rom_version.extracted_region_from_rom)

        if self.rom_version.icon_url:
            self.image_loader.load_image_to_label(self.rom_version.icon_url)
        else:
            self.image_loader.remove_cover()

    def load_cover(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona Copertina Locale", "", "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)")
        if filepath:
            self.image_loader.load_image_to_label(filepath)
    
    def search_gametdb_cover_dialog(self):
        game_id = self.game_id_edit.text().strip()
        self.image_loader.search_gametdb_cover(game_id)

    def remove_cover(self):
        self.image_loader.remove_cover()

    def get_updated_rom_version(self) -> RomVersion:
        self.rom_version.region = self.region_combo.currentText()
        self.rom_version.version = self.version_edit.text().strip()
        self.rom_version.icon_url = self.image_loader.current_cover_path
        return self.rom_version

class AddRegionalRomDialog(QDialog):
    def __init__(self, game_name: str, game_id: str, game_creator: str, base_url: str, parent=None):
        super().__init__(parent)
        self.game_name = game_name
        self.game_id = game_id
        self.game_creator = game_creator
        self.base_url = base_url
        self.current_nds_path = None
        self.nds_info = None
        self.file_manager = FileManager(self.base_url)
        self.new_rom_version = None

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        self.setWindowTitle(f"Aggiungi Versione Regionale per '{self.game_name}'")
        self.setFixedSize(600, 700)
        layout = QVBoxLayout(self)

        info_group = QGroupBox("Informazioni Gioco Principale")
        info_layout = QGridLayout(info_group)
        info_layout.addWidget(QLabel("Nome Gioco:"), 0, 0)
        info_layout.addWidget(QLabel(self.game_name), 0, 1)
        info_layout.addWidget(QLabel("Game ID di Riferimento:"), 1, 0)
        info_layout.addWidget(QLabel(self.game_id), 1, 1)
        info_layout.addWidget(QLabel("Creatore Gioco Principale:"), 2, 0)
        info_layout.addWidget(QLabel(self.game_creator), 2, 1)
        layout.addWidget(info_group)

        file_group = QGroupBox("Carica File ROM")
        file_layout = QGridLayout(file_group)
        file_layout.addWidget(QLabel("File NDS:"), 0, 0)
        self.nds_path_label = QLabel("Nessun file selezionato")
        file_layout.addWidget(self.nds_path_label, 0, 1)
        self.load_nds_button = QPushButton("Seleziona NDS")
        self.load_nds_button.clicked.connect(self.load_nds_file)
        file_layout.addWidget(self.load_nds_button, 0, 2)
        layout.addWidget(file_group)

        rom_details_group = QGroupBox("Dettagli Nuova ROM Caricata")
        rom_details_layout = QGridLayout(rom_details_group)
        self.rom_title_label = QLabel("Titolo ROM: N/A")
        self.rom_details_game_id_label = QLabel("Game ID ROM: N/A")
        self.rom_maker_code_label = QLabel("Creatore ROM: N/A")
        self.rom_version_label = QLabel("Versione ROM: N/A")
        self.rom_extracted_region_label = QLabel("Regione ROM (da ID): N/A")
        
        rom_details_layout.addWidget(self.rom_title_label, 0, 0, 1, 2)
        rom_details_layout.addWidget(self.rom_details_game_id_label, 1, 0, 1, 2)
        rom_details_layout.addWidget(self.rom_maker_code_label, 2, 0, 1, 2)
        rom_details_layout.addWidget(self.rom_version_label, 3, 0, 1, 2)
        rom_details_layout.addWidget(self.rom_extracted_region_label, 4, 0, 1, 2)
        layout.addWidget(rom_details_group)

        cover_group = QGroupBox("Copertina")
        cover_layout = QHBoxLayout(cover_group)
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(DS_SCREEN_WIDTH // 2, DS_SCREEN_HEIGHT // 2)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText("Nessuna Copertina")
        cover_layout.addWidget(self.cover_label)
        
        self.image_loader = ImageLoader(self.cover_label)

        cover_buttons = QVBoxLayout()
        self.load_cover_btn = QPushButton("Carica Copertina Locale")
        self.load_cover_btn.clicked.connect(self.load_cover)
        cover_buttons.addWidget(self.load_cover_btn)
        self.search_gametdb_btn = QPushButton("Cerca GameTDB")
        self.search_gametdb_btn.clicked.connect(self.search_gametdb_cover)
        cover_buttons.addWidget(self.search_gametdb_btn)
        self.remove_cover_btn = QPushButton("Rimuovi Copertina")
        self.remove_cover_btn.clicked.connect(self.remove_cover)
        cover_buttons.addWidget(self.remove_cover_btn)
        cover_layout.addLayout(cover_buttons)
        layout.addWidget(cover_group)

        region_group = QGroupBox("Configura Regione")
        region_layout = QGridLayout(region_group)
        region_layout.addWidget(QLabel("Regione per questa ROM:"), 0, 0)
        self.region_combo = QComboBox()
        self.region_combo.addItems(["ANY", "EUR", "USA", "JPN", "CHI", "AUS"])
        region_layout.addWidget(self.region_combo, 0, 1)
        layout.addWidget(region_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_entry)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setEnabled(False)
        layout.addWidget(buttons)

    def load_initial_data(self):
        if len(self.game_id) >= 4:
            fourth_char = self.game_id[3].upper()
            game_id_region_map = {
                'A': "ANY", 'B': "ANY", 'C': "CHI", 'D': "EUR", 'E': "USA", 
                'F': "EUR", 'G': "ANY", 'H': "EUR", 'I': "EUR", 'J': "JPN", 
                'K': "ANY", 'L': "USA", 'M': "EUR", 'N': "EUR", 'O': "ANY", 
                'P': "EUR", 'Q': "DA", 'R': "RU", 'S': "ES", 'T': "USA", 
                'U': "AUS", 'V': "EUR", 'W': "EUR", 'X': "EUR", 'Y': "EUR", 'Z': "EUR"
            }
            initial_region = game_id_region_map.get(fourth_char, "ANY")
            region_index = self.region_combo.findText(initial_region)
            if region_index >= 0:
                self.region_combo.setCurrentIndex(region_index)

    def load_nds_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona File NDS", "", "File NDS (*.nds *.dsi *.zip);;Tutti i file (*)")
        if filepath:
            original_filename = os.path.basename(filepath)
            self.current_nds_path = None
            extracted_rom_path = None
            self.temp_zip_extraction_dir = None

            if filepath.lower().endswith('.zip'):
                try:
                    self.temp_zip_extraction_dir = Path(tempfile.mkdtemp())
                    with zipfile.ZipFile(filepath, 'r') as zip_ref:
                        zip_ref.extractall(self.temp_zip_extraction_dir)
                    
                    largest_rom_path = None
                    largest_rom_size = -1

                    for root, _, files in os.walk(self.temp_zip_extraction_dir):
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
                        self.ok_button.setEnabled(False)
                        if self.temp_zip_extraction_dir and self.temp_zip_extraction_dir.exists():
                            shutil.rmtree(self.temp_zip_extraction_dir)
                            self.temp_zip_extraction_dir = None
                        return
                except Exception as e:
                    QMessageBox.critical(self, "Errore", f"Errore durante l'estrazione o la gestione del file ZIP: {e}")
                    self.ok_button.setEnabled(False)
                    if self.temp_zip_extraction_dir and self.temp_zip_extraction_dir.exists():
                        shutil.rmtree(self.temp_zip_extraction_dir)
                        self.temp_zip_extraction_dir = None
                    return
            else:
                extracted_rom_path = filepath
                self.nds_path_label.setText(original_filename)

            self.current_nds_path = extracted_rom_path
            try:
                self.nds_info = NDSExtractor.extract_info(self.current_nds_path)
                
                self.rom_title_label.setText(f"Titolo ROM: {self.nds_info.title}")
                self.rom_details_game_id_label.setText(f"Game ID ROM: {self.nds_info.game_id}")
                self.rom_maker_code_label.setText(f"Creatore ROM: {self.nds_info.maker_code}")
                self.rom_version_label.setText(f"Versione ROM: {self.nds_info.rom_version}")
                self.rom_extracted_region_label.setText(f"Regione ROM (da ID): {self.nds_info.region_from_rom}")

                region_index = self.region_combo.findText(self.nds_info.region_from_rom)
                if region_index >= 0:
                    self.region_combo.setCurrentIndex(region_index)
                else:
                    self.region_combo.setCurrentIndex(self.region_combo.findText("ANY"))

                self.ok_button.setEnabled(True)
                self.image_loader.search_gametdb_cover(self.nds_info.game_id, auto_search=True)

            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore leggendo il file NDS: {e}")
                self.ok_button.setEnabled(False)
                self.nds_info = None
                self.rom_title_label.setText("Titolo ROM: N/A")
                self.rom_details_game_id_label.setText("Game ID ROM: N/A")
                self.rom_maker_code_label.setText("Creatore ROM: N/A")
                self.rom_version_label.setText("Versione ROM: N/A")
                self.rom_extracted_region_label.setText("Regione ROM (da ID): N/A")
        else:
            self.ok_button.setEnabled(False)
            self.nds_info = None
            self.rom_title_label.setText("Titolo ROM: N/A")
            self.rom_details_game_id_label.setText("Game ID ROM: N/A")
            self.rom_maker_code_label.setText("Creatore ROM: N/A")
            self.rom_version_label.setText("Versione ROM: N/A")
            self.rom_extracted_region_label.setText("Regione ROM (da ID): N/A")

    def load_cover(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona Copertina Locale", "", "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)")
        if filepath:
            self.image_loader.load_image_to_label(filepath)

    def search_gametdb_cover(self, auto_search=False):
        game_id = self.nds_info.game_id if self.nds_info else ""
        self.image_loader.search_gametdb_cover(game_id, auto_search)

    def remove_cover(self):
        self.image_loader.remove_cover()

    def accept_entry(self):
        if not self.current_nds_path or not self.nds_info:
            QMessageBox.warning(self, "Errore", "Seleziona e carica un file NDS valido.")
            return

        new_rom_version = RomVersion(
            region=self.region_combo.currentText(),
            version=str(self.nds_info.rom_version),
            game_id=self.nds_info.game_id,
            extracted_region_from_rom=self.nds_info.region_from_rom
        )
        
        rom_url, actual_rom_filename_on_disk = self.file_manager.copy_rom_file(
            self.current_nds_path, new_rom_version.internal_file_id
        )
        new_rom_version.download_url = rom_url
        new_rom_version.filename = actual_rom_filename_on_disk
        new_rom_version.filesize = str(os.path.getsize(self.current_nds_path))

        cover_url_to_save = ""
        if self.image_loader.current_cover_path:
            if self.image_loader.current_cover_path.startswith('http'):
                cover_url_to_save = self.image_loader.current_cover_path
            else:
                cover_url_to_save = self.file_manager.copy_local_cover_file(
                    self.image_loader.current_cover_path, new_rom_version.internal_file_id
                )
        new_rom_version.icon_url = cover_url_to_save
        
        self.new_rom_version = new_rom_version
        self.accept()


class FileManager:
    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip('/')
        self.roms_dir = Path("assets/roms")
        self.covers_dir = Path("assets/covers")
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
    
    def remove_rom_file(self, file_identifier: str):
        for rom_file in self.roms_dir.glob(f"{file_identifier}.*"):
            if rom_file.suffix.lower() in ['.nds', '.dsi']:
                try:
                    rom_file.unlink()
                except OSError as e:
                    print(f"Errore eliminando file ROM {rom_file}: {e}")

class NDSDatabaseManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.json_database_path = "database.json"
        self.txt_database_path = "database.txt"
        self.url_path = "url.txt"
        self.entries: List[GameEntry] = []
        self.base_url = ""
        self.current_nds_path = None
        self.image_loader_add_tab = None 
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

        self.image_loader_add_tab = ImageLoader(self.cover_preview, self.statusBar().showMessage)

        info_group = QGroupBox("Informazioni ROM")
        info_layout = QGridLayout(info_group)
        row = 0
        info_layout.addWidget(QLabel("Nome:"), row, 0)
        self.name_edit = QLineEdit()
        info_layout.addWidget(self.name_edit, row, 1); row += 1

        info_layout.addWidget(QLabel("Versione (da ROM):"), row, 0)
        self.version_edit = QLineEdit()
        info_layout.addWidget(self.version_edit, row, 1); row += 1

        info_layout.addWidget(QLabel("Creatore (da ROM):"), row, 0)
        self.creator_edit = QLineEdit()
        info_layout.addWidget(self.creator_edit, row, 1); row += 1

        info_layout.addWidget(QLabel("Piattaforma:"), row, 0)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["nds", "dsi"])
        info_layout.addWidget(self.platform_combo, row, 1); row += 1

        info_layout.addWidget(QLabel("Regione (Utente):"), row, 0)
        self.region_combo = QComboBox()
        self.region_combo.addItems(["ANY", "EUR", "USA", "JPN", "CHI", "AUS"])
        info_layout.addWidget(self.region_combo, row, 1); row += 1

        info_layout.addWidget(QLabel("Game ID:"), row, 0)
        self.game_id_edit = QLineEdit()
        self.game_id_edit.setReadOnly(True)
        info_layout.addWidget(self.game_id_edit, row, 1); row += 1

        info_layout.addWidget(QLabel("Regione (da ROM):"), row, 0)
        self.extracted_region_label_add_tab = QLabel("N/A")
        info_layout.addWidget(self.extracted_region_label_add_tab, row, 1); row += 1

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
        list_layout.addWidget(QLabel("Giochi nel Database:"))
        self.rom_list = QListWidget()
        self.rom_list.itemClicked.connect(self.on_game_selected)
        list_layout.addWidget(self.rom_list)
        list_buttons = QHBoxLayout()
        self.delete_button = QPushButton("Elimina Gioco Completo")
        self.delete_button.clicked.connect(self.delete_selected_game)
        self.delete_button.setEnabled(False)
        list_buttons.addWidget(self.delete_button)
        list_layout.addLayout(list_buttons)
        splitter.addWidget(list_widget)
        
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.addWidget(QLabel("Dettagli Versione ROM Selezionata:"))
        self.details_cover = QLabel()
        self.details_cover.setFixedSize(DS_SCREEN_WIDTH, DS_SCREEN_HEIGHT)
        self.details_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
        details_layout.addWidget(self.details_cover)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        details_layout.addWidget(self.details_text)

        details_layout.addWidget(QLabel("Versioni Regionali dello Stesso Gioco:"))
        self.related_roms_list = QListWidget()
        self.related_roms_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.related_roms_list.setMaximumHeight(150)
        self.related_roms_list.itemClicked.connect(self.on_regional_rom_selected)
        details_layout.addWidget(self.related_roms_list)

        related_buttons_layout = QHBoxLayout()
        self.add_regional_rom_button = QPushButton("Aggiungi Nuova Versione Regionale")
        self.add_regional_rom_button.clicked.connect(self.add_new_regional_rom)
        self.add_regional_rom_button.setEnabled(False)
        related_buttons_layout.addWidget(self.add_regional_rom_button)

        self.edit_regional_rom_button = QPushButton("Modifica Versione Selezionata")
        self.edit_regional_rom_button.clicked.connect(self.edit_selected_regional_rom)
        self.edit_regional_rom_button.setEnabled(False)
        related_buttons_layout.addWidget(self.edit_regional_rom_button)

        self.delete_regional_rom_button = QPushButton("Elimina Versione Selezionata")
        self.delete_regional_rom_button.clicked.connect(self.delete_selected_regional_rom)
        self.delete_regional_rom_button.setEnabled(False)
        related_buttons_layout.addWidget(self.delete_regional_rom_button)
        
        details_layout.addLayout(related_buttons_layout)


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

    def load_nds_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona File NDS", "", "File NDS (*.nds *.dsi *.zip);;Tutti i file (*)")
        if filepath:
            original_filename = os.path.basename(filepath)
            self.current_nds_path = None
            extracted_rom_path = None
            self.temp_zip_extraction_dir = None

            if filepath.lower().endswith('.zip'):
                try:
                    self.temp_zip_extraction_dir = Path(tempfile.mkdtemp())
                    with zipfile.ZipFile(filepath, 'r') as zip_ref:
                        zip_ref.extractall(self.temp_zip_extraction_dir)
                    
                    largest_rom_path = None
                    largest_rom_size = -1

                    for root, _, files in os.walk(self.temp_zip_extraction_dir):
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
                        if self.temp_zip_extraction_dir and self.temp_zip_extraction_dir.exists():
                            shutil.rmtree(self.temp_zip_extraction_dir)
                            self.temp_zip_extraction_dir = None
                        return
                except Exception as e:
                    QMessageBox.critical(self, "Errore", f"Errore durante l'estrazione o la gestione del file ZIP: {e}")
                    self.add_button.setEnabled(False)
                    if self.temp_zip_extraction_dir and self.temp_zip_extraction_dir.exists():
                        shutil.rmtree(self.temp_zip_extraction_dir)
                        self.temp_zip_extraction_dir = None
                    return
            else:
                extracted_rom_path = filepath
                self.nds_path_label.setText(original_filename)

            self.current_nds_path = extracted_rom_path
            try:
                nds_info = NDSExtractor.extract_info(self.current_nds_path)
                self.name_edit.setText(nds_info.title)
                self.game_id_edit.setText(nds_info.game_id)
                self.creator_edit.setText(nds_info.maker_code)
                self.version_edit.setText(str(nds_info.rom_version))
                self.extracted_region_label_add_tab.setText(nds_info.region_from_rom)

                region_index = self.region_combo.findText(nds_info.region_from_rom)
                if region_index >= 0:
                    self.region_combo.setCurrentIndex(region_index)
                else:
                    self.region_combo.setCurrentIndex(self.region_combo.findText("ANY"))

                self.add_button.setEnabled(True)
                self.image_loader_add_tab.search_gametdb_cover(nds_info.game_id, auto_search=True)

            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore leggendo il file NDS: {e}")
                self.add_button.setEnabled(False)
        else:
            self.add_button.setEnabled(False)

    def load_cover_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleziona Copertina Locale", "", "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)")
        if filepath:
            self.image_loader_add_tab.load_image_to_label(filepath)

    def search_gametdb_cover(self, auto_search=False):
        game_id = self.game_id_edit.text().strip()
        self.image_loader_add_tab.search_gametdb_cover(game_id, auto_search)

    def add_to_database(self):
        if not self.current_nds_path:
            QMessageBox.warning(self, "Errore", "Seleziona prima un file NDS!")
            return
        
        try:
            if not self.image_loader_add_tab.current_cover_path:
                reply = QMessageBox.question(self, "Nessuna Copertina",
                                            "Nessuna copertina automatica trovata e non ne hai selezionata una manualmente.\nVuoi continuare senza copertina o vuoi selezionarne una ora?",
                                            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.No,
                                            QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Open:
                    self.load_cover_file()
                    if not self.image_loader_add_tab.current_cover_path:
                        return
                elif reply == QMessageBox.StandardButton.No:
                    pass
        except AttributeError as e:
            QMessageBox.critical(self.add_tab, "Errore di inizializzazione", 
                                 f"Errore durante l'accesso al caricatore di immagini: {e}. "
                                 "Assicurati che 'image_loader_add_tab' sia stato inizializzato correttamente. "
                                 "Potrebbe esserci un errore di battitura (es. 'image_loader' invece di 'image_loader_add_tab') "
                                 "o un problema con l'ordine di inizializzazione.")
            return
            
        try:
            nds_info = NDSExtractor.extract_info(self.current_nds_path)

            new_rom_version = RomVersion(
                region=self.region_combo.currentText(),
                version=self.version_edit.text().strip() or str(nds_info.rom_version),
                game_id=self.game_id_edit.text().strip() or nds_info.game_id,
                extracted_region_from_rom=self.extracted_region_label_add_tab.text() or nds_info.region_from_rom
            )

            rom_url, actual_rom_filename_on_disk = self.file_manager.copy_rom_file(
                self.current_nds_path, new_rom_version.internal_file_id
            )
            new_rom_version.download_url = rom_url
            new_rom_version.filename = actual_rom_filename_on_disk
            new_rom_version.filesize = str(os.path.getsize(self.current_nds_path))

            cover_url_to_save = ""
            if self.image_loader_add_tab.current_cover_path:
                if self.image_loader_add_tab.current_cover_path.startswith('http'):
                    cover_url_to_save = self.image_loader_add_tab.current_cover_path
                else:
                    cover_url_to_save = self.file_manager.copy_local_cover_file(
                        self.image_loader_add_tab.current_cover_path, new_rom_version.internal_file_id
                    )
            new_rom_version.icon_url = cover_url_to_save

            existing_game_entry = next((ge for ge in self.entries if ge.game_id == new_rom_version.game_id), None)

            if existing_game_entry:
                existing_game_entry.rom_versions.append(new_rom_version)
                QMessageBox.information(self, "Successo", f"Nuova versione regionale '{new_rom_version.region}' aggiunta al gioco '{existing_game_entry.name}'.")
            else:
                new_game_entry = GameEntry(
                    name=self.name_edit.text().strip() or nds_info.title or "Gioco Senza Nome",
                    creator=self.creator_edit.text().strip() or nds_info.maker_code,
                    platform=self.platform_combo.currentText(),
                    game_id=new_rom_version.game_id,
                    rom_versions=[new_rom_version]
                )
                self.entries.append(new_game_entry)
                QMessageBox.information(self, "Successo", f"Nuovo gioco '{new_game_entry.name}' aggiunto con la prima versione regionale '{new_rom_version.region}'.")
            
            self.clear_fields()
            self.refresh_rom_list()
            self.save_database()
            self.statusBar().showMessage(f"ROM '{new_rom_version.filename}' aggiunta al database")
            
        except Exception as e:
            QMessageBox.critical(self.add_tab, "Errore", f"Errore aggiungendo la ROM: {e}")
        finally:
            if hasattr(self, 'temp_zip_extraction_dir') and self.temp_zip_extraction_dir and self.temp_zip_extraction_dir.exists():
                shutil.rmtree(self.temp_zip_extraction_dir)
                self.temp_zip_extraction_dir = None
    
    def clear_fields(self):
        self.current_nds_path = None
        if hasattr(self, 'temp_zip_extraction_dir') and self.temp_zip_extraction_dir and self.temp_zip_extraction_dir.exists():
            shutil.rmtree(self.temp_zip_extraction_dir)
            self.temp_zip_extraction_dir = None
        
        self.nds_path_label.setText("Nessun file selezionato")
        self.cover_path_label.setText("Nessuna copertina")
        if self.image_loader_add_tab: 
            self.image_loader_add_tab.remove_cover()
        
        self.name_edit.clear()
        self.version_edit.clear()
        self.creator_edit.clear()
        self.platform_combo.setCurrentIndex(0)
        self.region_combo.setCurrentIndex(0)
        self.game_id_edit.clear()
        self.extracted_region_label_add_tab.setText("N/A")
        
        self.add_button.setEnabled(False)
    
    def refresh_rom_list(self):
        self.rom_list.clear()
        self.rom_list.setIconSize(QSize(LIST_ICON_SIZE, LIST_ICON_SIZE))
        
        self.entries.sort(key=lambda x: x.name.lower())

        for game_entry in self.entries:
            display_name = game_entry.name
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, game_entry.id)

            if game_entry.rom_versions:
                first_rom_version = game_entry.rom_versions[0]
                if first_rom_version.icon_url:
                    pixmap = QPixmap()
                    if first_rom_version.icon_url.startswith('http'):
                        if pixmap.load(first_rom_version.icon_url):
                            pixmap = pixmap.scaled(LIST_ICON_SIZE, LIST_ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            item.setIcon(QIcon(pixmap))
                        else:
                            print(f"Errore caricando icona remota per lista {first_rom_version.icon_url}")
                    else:
                        cover_file = Path(first_rom_version.icon_url)
                        if cover_file.exists():
                            try:
                                pil_image = Image.open(str(cover_file))
                                pil_image.thumbnail((LIST_ICON_SIZE, LIST_ICON_SIZE), Image.LANCZOS)
                                pixmap = pil_to_qpixmap(pil_image)
                                item.setIcon(QIcon(pixmap))
                            except Exception as e:
                                print(f"Errore caricando icona per lista (locale) {cover_file}: {e}")
            self.rom_list.addItem(item)
    
    def on_game_selected(self, item):
        game_id = item.data(Qt.ItemDataRole.UserRole)
        if not game_id:
            return

        selected_game_entry = next((ge for ge in self.entries if ge.id == game_id), None)
        if not selected_game_entry:
            return

        self.related_roms_list.clear()
        
        if selected_game_entry.rom_versions:
            selected_game_entry.rom_versions.sort(key=lambda x: x.region)
            for rom_version in selected_game_entry.rom_versions:
                display_name = rom_version.region
                related_item = QListWidgetItem(display_name)
                related_item.setData(Qt.ItemDataRole.UserRole, rom_version.id)
                self.related_roms_list.addItem(related_item)
            
            self.related_roms_list.setCurrentRow(0)
            self.on_regional_rom_selected(self.related_roms_list.currentItem())
        else:
            self.related_roms_list.addItem("Nessuna versione regionale per questo gioco.")
            self.details_cover.clear()
            self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
            self.details_text.clear()
            self.edit_regional_rom_button.setEnabled(False)
            self.delete_regional_rom_button.setEnabled(False)


        self.delete_button.setEnabled(True)
        self.add_regional_rom_button.setEnabled(True)
        
    def on_regional_rom_selected(self, item):
        rom_version_id = item.data(Qt.ItemDataRole.UserRole)
        if not rom_version_id:
            return

        selected_rom_version = None
        for game_entry in self.entries:
            for rv in game_entry.rom_versions:
                if rv.id == rom_version_id:
                    selected_rom_version = rv
                    break
            if selected_rom_version:
                break
        
        if selected_rom_version:
            self.show_rom_details(selected_rom_version)
            self.edit_regional_rom_button.setEnabled(True)
            self.delete_regional_rom_button.setEnabled(True)
        else:
            self.details_cover.clear()
            self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
            self.details_text.clear()
            self.edit_regional_rom_button.setEnabled(False)
            self.delete_regional_rom_button.setEnabled(False)


    def show_rom_details(self, rom_version: RomVersion):
        self.details_cover.clear()
        self.details_cover.setText("Caricamento...")

        if rom_version.icon_url:
            pixmap = QPixmap()
            if rom_version.icon_url.startswith('http'):
                try:
                    response = requests.get(rom_version.icon_url, timeout=5)
                    response.raise_for_status()
                    pixmap.loadFromData(response.content)
                    if not pixmap.isNull():
                        pixmap = pixmap.scaled(DS_SCREEN_WIDTH, DS_SCREEN_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.details_cover.setPixmap(pixmap)
                    else:
                        self.details_cover.setText("Errore caricamento remoto")
                except requests.exceptions.RequestException as e:
                    self.details_cover.setText(f"Errore caricamento remoto: {e}")
            else:
                cover_file = Path(rom_version.icon_url)
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
        
        parent_game_entry = next((ge for ge in self.entries for rv in ge.rom_versions if rv.id == rom_version.id), None)
        game_name = parent_game_entry.name if parent_game_entry else "N/A"
        game_creator = parent_game_entry.creator if parent_game_entry else "N/A"
        
        details_text = f"""Nome Gioco: {game_name}
Creatore Gioco: {game_creator}
Piattaforma: {parent_game_entry.platform if parent_game_entry else 'N/A'}
---
Dettagli Versione ROM:
Regione (Utente): {rom_version.region}
Versione (da ROM): {rom_version.version}
Game ID: {rom_version.game_id}
Regione (da ROM): {rom_version.extracted_region_from_rom}
Filename ROM (su disco): {rom_version.filename}
Dimensione ROM: {rom_version.filesize} bytes
URL Download ROM: {rom_version.download_url}
URL Copertina: {rom_version.icon_url if rom_version.icon_url else 'N/A'}
ID Interno (per file): {rom_version.internal_file_id}"""
        
        self.details_text.setPlainText(details_text)
    
    def add_new_regional_rom(self):
        current_game_item = self.rom_list.currentItem()
        if not current_game_item:
            QMessageBox.warning(self, "Avviso", "Seleziona prima un gioco dalla lista principale per aggiungere una versione regionale.")
            return
        
        game_id_from_item = current_game_item.data(Qt.ItemDataRole.UserRole)
        selected_game_entry = next((ge for ge in self.entries if ge.id == game_id_from_item), None)
        
        if not selected_game_entry:
            QMessageBox.warning(self, "Errore", "Impossibile trovare i dati del gioco principale per aggiungere una versione regionale.")
            return

        dialog = AddRegionalRomDialog(selected_game_entry.name, selected_game_entry.game_id, selected_game_entry.creator, self.base_url, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_rom_version = dialog.new_rom_version
            if new_rom_version:
                selected_game_entry.rom_versions.append(new_rom_version)
                self.refresh_rom_list()
                self.save_database()
                QMessageBox.information(self, "Successo", f"Nuova versione regionale '{new_rom_version.region}' aggiunta al gioco '{selected_game_entry.name}'.")
                
                for i in range(self.rom_list.count()):
                    item = self.rom_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == selected_game_entry.id:
                        self.rom_list.setCurrentItem(item)
                        self.on_game_selected(item)
                        break

    def edit_selected_game(self):
        QMessageBox.information(self, "Informazione", "La modifica del 'gioco completo' non è supportata direttamente. Modifica le singole versioni regionali.")
        return

    def edit_selected_regional_rom(self):
        current_rom_item = self.related_roms_list.currentItem()
        if not current_rom_item:
            QMessageBox.warning(self, "Avviso", "Seleziona una versione regionale dalla lista per modificarla.")
            return
        
        rom_version_id_to_edit = current_rom_item.data(Qt.ItemDataRole.UserRole)
        rom_version_to_edit = None
        parent_game_entry = None
        for ge in self.entries:
            for rv in ge.rom_versions:
                if rv.id == rom_version_id_to_edit:
                    rom_version_to_edit = rv
                    parent_game_entry = ge
                    break
            if rom_version_to_edit:
                break
        
        if not rom_version_to_edit:
            return
        
        dialog = EditDialog(rom_version_to_edit, self.base_url, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_rom_version = dialog.get_updated_rom_version()
            
            if not rom_version_to_edit.icon_url.startswith('http') and (updated_rom_version.icon_url.startswith('http') or not updated_rom_version.icon_url):
                self.file_manager.remove_local_cover_file(updated_rom_version.internal_file_id)
            if updated_rom_version.icon_url and not updated_rom_version.icon_url.startswith('http'):
                new_local_url = self.file_manager.copy_local_cover_file(updated_rom_version.icon_url, updated_rom_version.internal_file_id)
                updated_rom_version.icon_url = new_local_url
            
            current_rom_item.setText(updated_rom_version.region)
            
            self.save_database()
            self.statusBar().showMessage(f"Versione regionale '{updated_rom_version.region}' del gioco '{parent_game_entry.name}' modificata.")
            
            self.show_rom_details(updated_rom_version)
            
            if parent_game_entry:
                for i in range(self.rom_list.count()):
                    item = self.rom_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == parent_game_entry.id:
                        self.rom_list.setCurrentItem(item)
                        self.on_game_selected(item)
                        for j in range(self.related_roms_list.count()):
                            r_item = self.related_roms_list.item(j)
                            if r_item.data(Qt.ItemDataRole.UserRole) == updated_rom_version.id:
                                self.related_roms_list.setCurrentItem(r_item)
                                break
                        break

    def delete_selected_game(self):
        current_game_item = self.rom_list.currentItem()
        if not current_game_item:
            return
        
        game_id_to_delete = current_game_item.data(Qt.ItemDataRole.UserRole)
        game_entry_to_delete = next((ge for ge in self.entries if ge.id == game_id_to_delete), None)
        
        if not game_entry_to_delete:
            QMessageBox.warning(self, "Errore", "Nessuno gioco trovato per l'elemento selezionato.")
            return

        reply = QMessageBox.question(
            self, "Conferma Eliminazione",
            f"Sei sicuro di voler eliminare TUTTE le versioni del gioco '{game_entry_to_delete.name}' (Game ID: {game_entry_to_delete.game_id})?\n\n"
            "Questo rimuoverà tutte le entry dal database e i file ROM e copertina fisici associati.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for rom_version in game_entry_to_delete.rom_versions:
                self.file_manager.remove_rom_file(rom_version.internal_file_id)
                self.file_manager.remove_local_cover_file(rom_version.internal_file_id)
            
            self.entries.remove(game_entry_to_delete)

            self.refresh_rom_list()
            
            self.details_cover.clear()
            self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
            self.details_text.clear()
            self.related_roms_list.clear()
            self.related_roms_list.addItem("Nessuna versione regionale per questo gioco.")
            
            self.delete_button.setEnabled(False)
            self.add_regional_rom_button.setEnabled(False)
            self.edit_regional_rom_button.setEnabled(False)
            self.delete_regional_rom_button.setEnabled(False)
            
            self.save_database()
            self.statusBar().showMessage(f"Tutte le ROM per il gioco '{game_entry_to_delete.name}' eliminate dal database e dal disco.")

    def delete_selected_regional_rom(self):
        current_rom_item = self.related_roms_list.currentItem()
        if not current_rom_item:
            QMessageBox.warning(self, "Avviso", "Seleziona una versione regionale dalla lista per eliminarla.")
            return
        
        rom_version_id_to_delete = current_rom_item.data(Qt.ItemDataRole.UserRole)
        rom_version_to_delete = None
        parent_game_entry = None
        for ge in self.entries:
            for rv in ge.rom_versions:
                if rv.id == rom_version_id_to_delete:
                    rom_version_to_delete = rv
                    parent_game_entry = ge
                    break
            if parent_game_entry:
                break
        
        if not rom_version_to_delete or not parent_game_entry:
            return
        
        reply = QMessageBox.question(
            self, "Conferma Eliminazione",
            f"Sei sicuro di voler eliminare la versione regionale '{rom_version_to_delete.region}' del gioco '{parent_game_entry.name}'?\n\n"
            "Questo rimuoverà l'entry dal database e i file ROM e copertina fisici.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.file_manager.remove_rom_file(rom_version_to_delete.internal_file_id)
            self.file_manager.remove_local_cover_file(rom_version_to_delete.internal_file_id)

            parent_game_entry.rom_versions.remove(rom_version_to_delete)
            
            if not parent_game_entry.rom_versions:
                self.entries.remove(parent_game_entry)
                QMessageBox.information(self, "Informazione", f"Il gioco '{parent_game_entry.name}' è stato rimosso in quanto non ha più versioni regionali.")

            self.refresh_rom_list()
            self.save_database()
            self.statusBar().showMessage(f"Versione regionale '{rom_version_to_delete.region}' del gioco '{parent_game_entry.name}' eliminata.")
            
            if parent_game_entry and parent_game_entry in self.entries:
                for i in range(self.rom_list.count()):
                    item = self.rom_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == parent_game_entry.id:
                        self.rom_list.setCurrentItem(item)
                        self.on_game_selected(item)
                        break
            else:
                self.details_cover.clear()
                self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
                self.details_text.clear()
                self.related_roms_list.clear()
                self.related_roms_list.addItem("Nessuna versione regionale per questo gioco.")
                self.edit_regional_rom_button.setEnabled(False)
                self.delete_regional_rom_button.setEnabled(False)


    def load_database(self):
        # Il caricamento si basa ora esclusivamente sul file JSON per semplicità.
        # Il file TXT è considerato un formato di esportazione semplificato.
        if os.path.exists(self.json_database_path):
            try:
                with open(self.json_database_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.entries = [GameEntry.from_dict(d) for d in data]
                self.refresh_rom_list()
                self.statusBar().showMessage(f"Database JSON caricato: {len(self.entries)} giochi")
                return
            except json.JSONDecodeError as e:
                QMessageBox.warning(self, "Errore JSON", f"Errore decodificando il database JSON: {e}. Il database verrà inizializzato.")
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore caricando il database JSON: {e}. Il database verrà inizializzato.")
        
        # Se il JSON non esiste o fallisce, crea un database vuoto.
        try:
            with open(self.json_database_path, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4)
            self.statusBar().showMessage(f"Database '{self.json_database_path}' creato.")
        except Exception as e:
            QMessageBox.warning(self, "Errore", f"Errore creando il database JSON: {e}")
    
    def save_database(self):
        try:
            with open(self.json_database_path, 'w', encoding='utf-8') as f:
                json.dump([entry.to_dict() for entry in self.entries], f, indent=4)

            with open(self.txt_database_path, 'w', encoding='utf-8') as f:
                f.write("1\n")
                f.write("\t\n")
                for game_entry in self.entries:
                    for line in game_entry.to_lines_for_txt():
                        f.write(line + '\n')
            
            self.statusBar().showMessage("Database salvato (JSON e TXT)")
            QMessageBox.information(
                self, "Successo", 
                f"Database salvato con successo!\n\n"
                f"- Versione JSON: {self.json_database_path}\n"
                f"- Versione completa TXT: {self.txt_database_path}"
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
