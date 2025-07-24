#!/usr/bin/env python3
"""
NDS Database Manager
Un'applicazione PyQt6 per gestire un database di file NDS homebrew con gestione file e URL
"""

import sys
import os
import struct
import shutil
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime
import urllib.parse

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog,
    QMessageBox, QGroupBox, QGridLayout, QProgressBar,
    QSpinBox, QComboBox, QListWidget, QListWidgetItem, QSplitter,
    QTabWidget, QScrollArea, QFrame, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QFont, QIcon


@dataclass
class NDSInfo:
    """Informazioni estratte da un file NDS"""
    title: str
    icon: Optional[bytes]
    filename: str
    filesize: int
    creator: str = ""
    version: str = ""
    download_url: str = ""
    icon_url: str = ""


class NDSExtractor:
    """Classe per estrarre informazioni dai file NDS"""
    
    @staticmethod
    def extract_info(filepath: str) -> NDSInfo:
        """Estrae informazioni da un file NDS"""
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        
        with open(filepath, 'rb') as f:
            # Leggi l'header NDS
            header = f.read(0x200)
            
            # Estrai il titolo (offset 0x00, 12 bytes)
            title_bytes = header[0x00:0x0C]
            title = title_bytes.decode('ascii', errors='ignore').strip('\x00')
            
            # Se il titolo è vuoto, usa il nome del file
            if not title:
                title = os.path.splitext(filename)[0]
            
            # Cerca di estrarre l'icona (banner)
            icon_data = None
            try:
                # Offset del banner nell'header (0x68)
                banner_offset = struct.unpack('<I', header[0x68:0x6C])[0]
                if banner_offset > 0:
                    f.seek(banner_offset)
                    banner_header = f.read(0x20)
                    
                    # Verifica se è un banner valido
                    if banner_header[:4] == b'\x01\x00\x00\x00':  # Banner version 1
                        # L'icona inizia a offset 0x20 dal banner
                        f.seek(banner_offset + 0x20)
                        icon_data = f.read(0x200)  # 32x32 4bpp icon
                        
                        # Leggi anche la palette
                        palette_data = f.read(0x20)  # 16 colors, 2 bytes each
                        icon_data = icon_data + palette_data
            except:
                pass
            
            return NDSInfo(
                title=title,
                icon=icon_data,
                filename=filename,
                filesize=filesize
            )


class DatabaseEntry:
    """Rappresenta una riga del database"""
    
    def __init__(self, line: str = ""):
        if line.strip():
            parts = line.strip().split('\t')
            self.id = parts[0] if len(parts) > 0 else ""
            self.name = parts[1] if len(parts) > 1 else ""
            self.platform = parts[2] if len(parts) > 2 else "nds"
            self.region = parts[3] if len(parts) > 3 else "ANY"
            self.version = parts[4] if len(parts) > 4 else ""
            self.creator = parts[5] if len(parts) > 5 else ""
            self.download_url = parts[6] if len(parts) > 6 else ""
            self.filename = parts[7] if len(parts) > 7 else ""
            self.filesize = parts[8] if len(parts) > 8 else "0"
            self.icon_url = parts[9] if len(parts) > 9 else ""
        else:
            self.id = ""
            self.name = ""
            self.platform = "nds"
            self.region = "ANY"
            self.version = ""
            self.creator = ""
            self.download_url = ""
            self.filename = ""
            self.filesize = "0"
            self.icon_url = ""
    
    def to_line(self) -> str:
        """Converte l'entry in una riga del database"""
        return f"{self.id}\t{self.name}\t{self.platform}\t{self.region}\t{self.version}\t{self.creator}\t{self.download_url}\t{self.filename}\t{self.filesize}\t{self.icon_url}"
    
    def to_line_relative(self) -> str:
        """Converte l'entry in una riga del database con URL relativi"""
        relative_download = self.download_url.split('/')[-1] if self.download_url else ""
        relative_icon = self.icon_url.split('/')[-1] if self.icon_url else ""
        return f"{self.id}\t{self.name}\t{self.platform}\t{self.region}\t{self.version}\t{self.creator}\t{relative_download}\t{self.filename}\t{self.filesize}\t{relative_icon}"


class EditDialog(QDialog):
    """Dialog per modificare una entry esistente"""
    
    def __init__(self, entry: DatabaseEntry, base_url: str, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.base_url = base_url
        self.cover_path = None
        self.init_ui()
        self.load_entry_data()
    
    def init_ui(self):
        self.setWindowTitle("Modifica Entry")
        self.setFixedSize(600, 500)
        
        layout = QVBoxLayout(self)
        
        # Cover preview
        cover_group = QGroupBox("Copertina")
        cover_layout = QHBoxLayout(cover_group)
        
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(128, 128)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid gray;")
        self.cover_label.setText("Nessuna\nCopertina")
        cover_layout.addWidget(self.cover_label)
        
        cover_buttons = QVBoxLayout()
        self.load_cover_btn = QPushButton("Carica Copertina")
        self.load_cover_btn.clicked.connect(self.load_cover)
        cover_buttons.addWidget(self.load_cover_btn)
        
        self.remove_cover_btn = QPushButton("Rimuovi Copertina")
        self.remove_cover_btn.clicked.connect(self.remove_cover)
        cover_buttons.addWidget(self.remove_cover_btn)
        
        cover_layout.addLayout(cover_buttons)
        layout.addWidget(cover_group)
        
        # Entry fields
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
        
        layout.addWidget(fields_group)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def load_entry_data(self):
        """Carica i dati dell'entry nei campi"""
        self.name_edit.setText(self.entry.name)
        self.version_edit.setText(self.entry.version)
        self.creator_edit.setText(self.entry.creator)
        
        platform_index = self.platform_combo.findText(self.entry.platform)
        if platform_index >= 0:
            self.platform_combo.setCurrentIndex(platform_index)
        
        region_index = self.region_combo.findText(self.entry.region)
        if region_index >= 0:
            self.region_combo.setCurrentIndex(region_index)
        
        # Carica copertina se esiste
        self.load_existing_cover()
    
    def load_existing_cover(self):
        """Carica la copertina esistente se disponibile"""
        covers_dir = Path("assets/covers")
        if covers_dir.exists():
            # Cerca file con lo stesso ID
            for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                cover_file = covers_dir / f"{self.entry.id}{ext}"
                if cover_file.exists():
                    pixmap = QPixmap(str(cover_file))
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.cover_label.setPixmap(scaled_pixmap)
                        self.cover_path = str(cover_file)
                    break
    
    def load_cover(self):
        """Carica una nuova copertina"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Seleziona Copertina", "", 
            "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)"
        )
        
        if filepath:
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.cover_label.setPixmap(scaled_pixmap)
                self.cover_path = filepath
            else:
                QMessageBox.warning(self, "Errore", "Impossibile caricare l'immagine selezionata.")
    
    def remove_cover(self):
        """Rimuove la copertina"""
        self.cover_label.clear()
        self.cover_label.setText("Nessuna\nCopertina")
        self.cover_path = None
    
    def get_updated_entry(self) -> DatabaseEntry:
        """Restituisce l'entry aggiornata"""
        self.entry.name = self.name_edit.text().strip()
        self.entry.version = self.version_edit.text().strip()
        self.entry.creator = self.creator_edit.text().strip()
        self.entry.platform = self.platform_combo.currentText()
        self.entry.region = self.region_combo.currentText()
        return self.entry


class FileManager:
    """Gestisce l'organizzazione dei file e la generazione degli URL"""
    
    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip('/')
        self.roms_dir = Path("assets/roms")
        self.covers_dir = Path("assets/covers")
        
        # Crea le directory se non esistono
        self.roms_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
    
    def copy_files(self, nds_path: str, cover_path: str, entry_id: str) -> tuple[str, str]:
        """Copia i file nelle directory appropriate e restituisce gli URL"""
        
        # Copia ROM
        nds_filename = f"{entry_id}_{Path(nds_path).name}"
        nds_dest = self.roms_dir / nds_filename
        shutil.copy2(nds_path, nds_dest)
        
        rom_url = f"{self.base_url}/assets/roms/{nds_filename}" if self.base_url else f"assets/roms/{nds_filename}"
        
        # Copia copertina se fornita
        cover_url = ""
        if cover_path and Path(cover_path).exists():
            cover_ext = Path(cover_path).suffix
            cover_filename = f"{entry_id}{cover_ext}"
            cover_dest = self.covers_dir / cover_filename
            shutil.copy2(cover_path, cover_dest)
            cover_url = f"{self.base_url}/assets/covers/{cover_filename}" if self.base_url else f"assets/covers/{cover_filename}"
        
        return rom_url, cover_url
    
    def update_cover(self, cover_path: str, entry_id: str) -> str:
        """Aggiorna solo la copertina per un entry esistente"""
        if not cover_path or not Path(cover_path).exists():
            return ""
        
        # Rimuovi copertine esistenti con questo ID
        for cover_file in self.covers_dir.glob(f"{entry_id}.*"):
            if cover_file.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                cover_file.unlink()
        
        # Copia nuova copertina
        cover_ext = Path(cover_path).suffix
        cover_filename = f"{entry_id}{cover_ext}"
        cover_dest = self.covers_dir / cover_filename
        shutil.copy2(cover_path, cover_dest)
        
        return f"{self.base_url}/assets/covers/{cover_filename}" if self.base_url else f"assets/covers/{cover_filename}"


class NDSDatabaseManager(QMainWindow):
    """Finestra principale dell'applicazione"""
    
    def __init__(self):
        super().__init__()
        self.database_path = "database.txt"
        self.url_path = "url.txt"
        self.entries = []
        self.base_url = ""
        self.file_manager = None
        self.current_nds_path = None
        self.current_cover_path = None
        
        self.load_base_url()
        self.file_manager = FileManager(self.base_url)
        
        self.init_ui()
        self.load_database()
    
    def load_base_url(self):
        """Carica l'URL base da url.txt"""
        if os.path.exists(self.url_path):
            try:
                with open(self.url_path, 'r', encoding='utf-8') as f:
                    self.base_url = f.read().strip()
            except Exception as e:
                print(f"Errore caricando URL base: {e}")
                self.base_url = ""
    
    def init_ui(self):
        """Inizializza l'interfaccia utente"""
        self.setWindowTitle("NDS Database Manager")
        self.setGeometry(100, 100, 1200, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Tab widget principale
        self.tab_widget = QTabWidget()
        central_widget_layout = QVBoxLayout(central_widget)
        central_widget_layout.addWidget(self.tab_widget)
        
        # Tab 1: Aggiungi nuova ROM
        self.add_tab = QWidget()
        self.tab_widget.addTab(self.add_tab, "Aggiungi ROM")
        self.init_add_tab()
        
        # Tab 2: Visualizza/Modifica ROM esistenti
        self.view_tab = QWidget()
        self.tab_widget.addTab(self.view_tab, "Gestisci ROM")
        self.init_view_tab()
        
        # Status bar
        self.statusBar().showMessage("Pronto")
    
    def init_add_tab(self):
        """Inizializza il tab per aggiungere nuove ROM"""
        layout = QVBoxLayout(self.add_tab)
        
        # URL base
        url_group = QGroupBox("Configurazione URL")
        url_layout = QHBoxLayout(url_group)
        
        url_layout.addWidget(QLabel("URL Base:"))
        self.base_url_edit = QLineEdit(self.base_url)
        self.base_url_edit.textChanged.connect(self.update_base_url)
        url_layout.addWidget(self.base_url_edit)
        
        layout.addWidget(url_group)
        
        # Sezione caricamento file
        file_group = QGroupBox("Carica File")
        file_layout = QGridLayout(file_group)
        
        # ROM NDS
        file_layout.addWidget(QLabel("File NDS:"), 0, 0)
        self.nds_path_label = QLabel("Nessun file selezionato")
        self.nds_path_label.setStyleSheet("color: gray;")
        file_layout.addWidget(self.nds_path_label, 0, 1)
        
        self.load_nds_button = QPushButton("Seleziona NDS")
        self.load_nds_button.clicked.connect(self.load_nds_file)
        file_layout.addWidget(self.load_nds_button, 0, 2)
        
        # Copertina
        file_layout.addWidget(QLabel("Copertina:"), 1, 0)
        self.cover_path_label = QLabel("Nessuna copertina")
        self.cover_path_label.setStyleSheet("color: gray;")
        file_layout.addWidget(self.cover_path_label, 1, 1)
        
        self.load_cover_button = QPushButton("Seleziona Copertina")
        self.load_cover_button.clicked.connect(self.load_cover_file)
        file_layout.addWidget(self.load_cover_button, 1, 2)
        
        layout.addWidget(file_group)
        
        # Anteprima copertina
        preview_group = QGroupBox("Anteprima Copertina")
        preview_layout = QHBoxLayout(preview_group)
        
        self.cover_preview = QLabel()
        self.cover_preview.setFixedSize(128, 128)
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setStyleSheet("border: 1px solid gray;")
        self.cover_preview.setText("Nessuna\nCopertina")
        preview_layout.addWidget(self.cover_preview)
        
        layout.addWidget(preview_group)
        
        # Sezione informazioni
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
        
        layout.addWidget(info_group)
        
        # Pulsanti azione
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
        """Inizializza il tab per visualizzare e modificare ROM esistenti"""
        layout = QHBoxLayout(self.view_tab)
        
        # Splitter per dividere lista e dettagli
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Lista ROM
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        
        list_layout.addWidget(QLabel("ROM nel Database:"))
        
        self.rom_list = QListWidget()
        self.rom_list.itemClicked.connect(self.on_rom_selected)
        list_layout.addWidget(self.rom_list)
        
        # Pulsanti per la lista
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
        
        # Dettagli ROM selezionata
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        
        details_layout.addWidget(QLabel("Dettagli ROM:"))
        
        # Anteprima copertina
        self.details_cover = QLabel()
        self.details_cover.setFixedSize(200, 200)
        self.details_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_cover.setStyleSheet("border: 1px solid gray;")
        self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
        details_layout.addWidget(self.details_cover)
        
        # Informazioni
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        details_layout.addWidget(self.details_text)
        
        splitter.addWidget(details_widget)
        
        # Imposta proporzioni splitter
        splitter.setSizes([400, 400])
        
        # Pulsanti azione globali
        global_buttons = QHBoxLayout()
        
        self.save_database_button = QPushButton("Salva Database")
        self.save_database_button.clicked.connect(self.save_database)
        global_buttons.addWidget(self.save_database_button)
        
        self.refresh_button = QPushButton("Aggiorna Lista")
        self.refresh_button.clicked.connect(self.refresh_rom_list)
        global_buttons.addWidget(self.refresh_button)
        
        layout.addLayout(global_buttons)
    
    def update_base_url(self):
        """Aggiorna l'URL base e salva in url.txt"""
        self.base_url = self.base_url_edit.text().strip()
        self.file_manager = FileManager(self.base_url)
        
        try:
            with open(self.url_path, 'w', encoding='utf-8') as f:
                f.write(self.base_url)
        except Exception as e:
            print(f"Errore salvando URL base: {e}")
    
    def load_nds_file(self):
        """Carica un file NDS"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Seleziona File NDS", "", "File NDS (*.nds *.dsi);;Tutti i file (*)"
        )
        
        if filepath:
            self.current_nds_path = filepath
            self.nds_path_label.setText(os.path.basename(filepath))
            self.nds_path_label.setStyleSheet("color: black;")
            
            # Estrai informazioni automaticamente
            try:
                nds_info = NDSExtractor.extract_info(filepath)
                self.name_edit.setText(nds_info.title)
                self.add_button.setEnabled(True)
                self.statusBar().showMessage(f"File NDS caricato: {nds_info.filename}")
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore leggendo il file NDS: {e}")
    
    def load_cover_file(self):
        """Carica un file copertina"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Seleziona Copertina", "", 
            "Immagini (*.png *.jpg *.jpeg *.gif *.bmp);;Tutti i file (*)"
        )
        
        if filepath:
            # Carica anteprima
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.cover_preview.setPixmap(scaled_pixmap)
                
                self.current_cover_path = filepath
                self.cover_path_label.setText(os.path.basename(filepath))
                self.cover_path_label.setStyleSheet("color: black;")
                self.statusBar().showMessage(f"Copertina caricata: {os.path.basename(filepath)}")
            else:
                QMessageBox.warning(self, "Errore", "Impossibile caricare l'immagine selezionata.")
    
    def add_to_database(self):
        """Aggiunge una nuova ROM al database"""
        if not self.current_nds_path:
            QMessageBox.warning(self, "Errore", "Seleziona prima un file NDS!")
            return
        
        # Genera ID incrementale
        max_id = 0
        for entry in self.entries:
            try:
                entry_id = int(entry.id)
                max_id = max(max_id, entry_id)
            except ValueError:
                pass
        
        new_id = str(max_id + 1)
        
        try:
            # Copia file e genera URL
            rom_url, cover_url = self.file_manager.copy_files(
                self.current_nds_path, self.current_cover_path, new_id
            )
            
            # Crea nuova entry
            entry = DatabaseEntry()
            entry.id = new_id
            entry.name = self.name_edit.text().strip() or "ROM Senza Nome"
            entry.version = self.version_edit.text().strip()
            entry.creator = self.creator_edit.text().strip()
            entry.platform = self.platform_combo.currentText()
            entry.region = self.region_combo.currentText()
            entry.download_url = rom_url
            entry.icon_url = cover_url
            entry.filename = os.path.basename(self.current_nds_path)
            entry.filesize = str(os.path.getsize(self.current_nds_path))
            
            # Aggiungi al database
            self.entries.append(entry)
            
            # Reset campi
            self.clear_fields()
            
            # Aggiorna lista
            self.refresh_rom_list()
            
            self.statusBar().showMessage(f"ROM '{entry.name}' aggiunta al database")
            QMessageBox.information(self, "Successo", f"ROM '{entry.name}' aggiunta con successo!")
            
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore aggiungendo la ROM: {e}")
    
    def clear_fields(self):
        """Pulisce tutti i campi"""
        self.current_nds_path = None
        self.current_cover_path = None
        
        self.nds_path_label.setText("Nessun file selezionato")
        self.nds_path_label.setStyleSheet("color: gray;")
        
        self.cover_path_label.setText("Nessuna copertina")
        self.cover_path_label.setStyleSheet("color: gray;")
        
        self.cover_preview.clear()
        self.cover_preview.setText("Nessuna\nCopertina")
        
        self.name_edit.clear()
        self.version_edit.clear()
        self.creator_edit.clear()
        self.platform_combo.setCurrentIndex(0)
        self.region_combo.setCurrentIndex(0)
        
        self.add_button.setEnabled(False)
    
    def refresh_rom_list(self):
        """Aggiorna la lista delle ROM"""
        self.rom_list.clear()
        
        for entry in self.entries:
            item = QListWidgetItem(f"{entry.id} - {entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.rom_list.addItem(item)
    
    def on_rom_selected(self, item):
        """Gestisce la selezione di una ROM dalla lista"""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry:
            self.show_rom_details(entry)
            self.edit_button.setEnabled(True)
            self.delete_button.setEnabled(True)
    
    def show_rom_details(self, entry: DatabaseEntry):
        """Mostra i dettagli di una ROM"""
        # Carica copertina se disponibile
        covers_dir = Path("assets/covers")
        cover_loaded = False
        
        if covers_dir.exists():
            for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                cover_file = covers_dir / f"{entry.id}{ext}"
                if cover_file.exists():
                    pixmap = QPixmap(str(cover_file))
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.details_cover.setPixmap(scaled_pixmap)
                        cover_loaded = True
                        break
        
        if not cover_loaded:
            self.details_cover.clear()
            self.details_cover.setText("Nessuna\nCopertina")
        
        # Mostra informazioni
        details_text = f"""
ID: {entry.id}
Nome: {entry.name}
Versione: {entry.version}
Creatore: {entry.creator}
Piattaforma: {entry.platform}
Regione: {entry.region}
Filename: {entry.filename}
Dimensione: {entry.filesize} bytes
URL Download: {entry.download_url}
URL Icona: {entry.icon_url}
        """.strip()
        
        self.details_text.setPlainText(details_text)
    
    def edit_selected_rom(self):
        """Modifica la ROM selezionata"""
        current_item = self.rom_list.currentItem()
        if not current_item:
            return
        
        entry = current_item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        
        dialog = EditDialog(entry, self.base_url, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Aggiorna entry
            updated_entry = dialog.get_updated_entry()
            
            # Aggiorna copertina se necessario
            if dialog.cover_path and dialog.cover_path != self.get_existing_cover_path(entry.id):
                cover_url = self.file_manager.update_cover(dialog.cover_path, entry.id)
                if cover_url:
                    updated_entry.icon_url = cover_url
            
            # Aggiorna lista e dettagli
            current_item.setText(f"{updated_entry.id} - {updated_entry.name}")
            self.show_rom_details(updated_entry)
            
            self.statusBar().showMessage(f"ROM '{updated_entry.name}' modificata")
    
    def get_existing_cover_path(self, entry_id: str) -> Optional[str]:
        """Trova il percorso della copertina esistente per un entry"""
        covers_dir = Path("assets/covers")
        if covers_dir.exists():
            for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                cover_file = covers_dir / f"{entry_id}{ext}"
                if cover_file.exists():
                    return str(cover_file)
        return None
    
    def delete_selected_rom(self):
        """Elimina la ROM selezionata"""
        current_item = self.rom_list.currentItem()
        if not current_item:
            return
        
        entry = current_item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        
        # Conferma eliminazione
        reply = QMessageBox.question(
            self, "Conferma Eliminazione",
            f"Sei sicuro di voler eliminare '{entry.name}'?\n\n"
            "Questo rimuoverà l'entry dal database ma NON eliminerà i file fisici.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Rimuovi dall'elenco
            self.entries.remove(entry)
            
            # Aggiorna lista
            self.refresh_rom_list()
            
            # Pulisci dettagli
            self.details_cover.clear()
            self.details_cover.setText("Seleziona una ROM\nper vedere i dettagli")
            self.details_text.clear()
            
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            
            self.statusBar().showMessage(f"ROM '{entry.name}' eliminata dal database")
    
    def load_database(self):
        """Carica il database esistente"""
        if os.path.exists(self.database_path):
            try:
                with open(self.database_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                self.entries = []
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.entries.append(DatabaseEntry(line))
                
                self.refresh_rom_list()
                self.statusBar().showMessage(f"Database caricato: {len(self.entries)} entries")
            except Exception as e:
                QMessageBox.warning(self, "Errore", f"Errore caricando il database: {e}")
    
    def save_database(self):
        """Salva il database in due versioni: completa e relativa"""
        try:
            # Salva versione completa (con URL assoluti)
            with open(self.database_path, 'w', encoding='utf-8') as f:
                for entry in self.entries:
                    f.write(entry.to_line() + '\n')
            
            # Salva versione relativa (senza base URL)
            relative_path = self.database_path.replace('.txt', '_relative.txt')
            with open(relative_path, 'w', encoding='utf-8') as f:
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
    
    # Imposta lo stile
    app.setStyle('Fusion')
    
    window = NDSDatabaseManager()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()