import os
import json
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.ttk import Progressbar, Button, Label, Entry, Style, Frame
from PIL import Image, ImageTk
import yt_dlp
import threading
import requests
from io import BytesIO

# Configuração do caminho de destino e histórico de downloads
config_file = 'config.json'
history_file = 'history.json'
translations_file = 'translations.json'

def load_config():
    if os.path.exists(os.path.join(os.getcwd(), config_file)):
        with open(os.path.join(os.getcwd(), config_file), 'r', encoding='utf-8') as file:
            return json.load(file)
    return {'destination': '', 'language': 'en'}

def save_config(config):
    with open(os.path.join(os.getcwd(), config_file), 'w', encoding='utf-8') as file:
        json.dump(config, file, ensure_ascii=False, indent=4)

def load_history():
    if os.path.exists(os.path.join(os.getcwd(), history_file)):
        with open(os.path.join(os.getcwd(), history_file), 'r', encoding='utf-8') as file:
            return json.load(file)
    return []

def save_history(history):
    with open(os.path.join(os.getcwd(), history_file), 'w', encoding='utf-8') as file:
        json.dump(history, file, ensure_ascii=False, indent=4)

def load_translations():
    if os.path.exists(os.path.join(os.getcwd(), translations_file)):
        with open(os.path.join(os.getcwd(), translations_file), 'r', encoding='utf-8') as file:
            return json.load(file)
    raise FileNotFoundError(f"Translations file '{translations_file}' not found.")

config = load_config()
history = load_history()
translations = load_translations()
download_thread = None
download_running = False
video_info_fetched = False
current_language = config.get('language', 'en')

# Função para traduzir texto
def translate(key):
    return translations[current_language].get(key, key)

# Função para escolher a pasta de destino
def choose_directory():
    directory = filedialog.askdirectory()
    if directory:
        destination_var.set(directory)
        config['destination'] = directory
        save_config(config)

# Função para remover códigos de escape ANSI
def remove_ansi_escape_sequences(text):
    return re.sub(r'\x1B[@-_][0-?]*[ -/]*[@-~]', '', text)

# Função para atualizar a barra de progresso
def update_progress(percent):
    progress_var.set(percent)
    progress_bar['value'] = percent
    root.update_idletasks()

# Função para atualizar as estatísticas do download
def update_stats(d):
    if d['status'] == 'downloading':
        percent_str = remove_ansi_escape_sequences(d['_percent_str']).strip().strip('%')
        try:
            percent = float(percent_str)
        except ValueError:
            percent = 0.0
        update_progress(percent)
        total_bytes = remove_ansi_escape_sequences(d.get('_total_bytes_str', 'Unknown')).strip()
        speed = remove_ansi_escape_sequences(d.get('_speed_str', 'Unknown')).strip()
        eta = remove_ansi_escape_sequences(d.get('_eta_str', 'Unknown')).strip()
        stats = translate('downloading').format(d['_percent_str'], total_bytes, speed, eta)
        stats_var.set(stats)
    elif d['status'] == 'finished':
        update_progress(100)
        stats_var.set(translate('download_complete'))
        add_to_history()
        toggle_button_state()
        show_open_location_button()
    elif d['status'] == 'error':
        stats_var.set(translate('error'))
        toggle_button_state()

# Função para validar URL
def validate_url(url):
    regex = re.compile(
        r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$'
    )
    return re.match(regex, url) is not None

# Função para buscar informações do vídeo
def fetch_video_info():
    global video_info_fetched
    url = url_var.get()
    if not url or not validate_url(url):
        messagebox.showerror(translate('error'), translate('invalid_url'))
        return

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            title = info_dict.get('title', translate('error'))
            thumbnail_url = info_dict.get('thumbnail')
            duration = info_dict.get('duration')
            formats = info_dict.get('formats', [])
            valid_formats = [f for f in formats if f.get('filesize') is not None]
            best_format = max(valid_formats, key=lambda x: x['filesize'])

        minutes, seconds = divmod(duration, 60)
        duration_str = f"{minutes} minutes and {seconds} seconds"

        size_str = f"{best_format['filesize'] / (1024 * 1024):.2f} MB" if 'filesize' in best_format else 'Unknown'

        info_var.set(f"{translate('title')}: {title}\n{translate('duration')}: {duration_str}\n{translate('quality')}: {best_format['format_note']}\n{translate('size')}: {size_str}")
        
        if thumbnail_url:
            response = requests.get(thumbnail_url)
            img_data = response.content
            img = Image.open(BytesIO(img_data))
            img = img.resize((160, 90), Image.ANTIALIAS)
            img = ImageTk.PhotoImage(img)
            thumbnail_label.config(image=img)
            thumbnail_label.image = img

        video_info_fetched = True
    except Exception as e:
        messagebox.showerror(translate('error'), f"{translate('fetch_error')} {e}")
        video_info_fetched = False

# Função para adicionar ao histórico
def add_to_history():
    url = url_var.get()
    destination = destination_var.get()
    info = info_var.get().split('\n')
    title = info[0].replace(f'{translate("title")}: ', '')

    if not any(item['url'] == url for item in history):
        history.append({
            'title': title,
            'url': url,
            'destination': destination
        })
        save_history(history)
        update_history_list()

# Função para baixar o vídeo/áudio
def download():
    global download_running, download_thread, video_info_fetched
    if not video_info_fetched:
        fetch_video_info()
        if not video_info_fetched:
            return

    if download_running:
        stop_download()
        return

    url = url_var.get()
    destination = destination_var.get()

    if not url or not validate_url(url):
        messagebox.showerror(translate('error'), translate('invalid_url'))
        return

    if not destination:
        messagebox.showerror(translate('error'), translate('choose_destination'))
        return

    ydl_opts = {
        'outtmpl': os.path.join(destination, '%(title)s.%(ext)s'),
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'progress_hooks': [update_stats],
    }

    def run_ydl():
        global download_running
        download_running = True
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            update_progress(100)
            stats_var.set(translate('download_complete'))
            add_to_history()
            show_open_location_button()
        except Exception as e:
            messagebox.showerror(translate('error'), str(e))
            stats_var.set(translate('error'))
        finally:
            download_running = False
            toggle_button_state()

    download_thread = threading.Thread(target=run_ydl)
    download_thread.start()
    stats_var.set(translate('download_status'))
    toggle_button_state()

# Função para parar o download
def stop_download():
    global download_running, download_thread
    if download_running and download_thread is not None:
        download_running = False
        stats_var.set(translate('download_status'))
        toggle_button_state()
    else:
        messagebox.showinfo(translate('error'), translate('no_download_running'))

# Função para alternar o estado do botão
def toggle_button_state():
    if download_running:
        download_button.config(text=translate('stop'), command=stop_download, style='TButton')
    else:
        download_button.config(text=translate('download'), command=download, style='Accent.TButton')

# Função para colar o link da área de transferência
def paste_link():
    url_var.set(root.clipboard_get())

# Função para abrir o local do arquivo
def open_download_location():
    path = destination_var.get()
    if os.path.isdir(path):
        os.startfile(path)
    else:
        messagebox.showerror(translate('error'), translate('choose_destination'))

# Função para mostrar o botão de abrir local
def show_open_location_button():
    open_location_button.grid(row=8, column=0, columnspan=3, padx=5, pady=10)

# Função para atualizar a lista de histórico
def update_history_list():
    for widget in history_frame.winfo_children():
        widget.destroy()

    for idx, item in enumerate(history):
        title = item['title']
        destination = item['destination']
        Label(history_frame, text=title, background='white').grid(row=idx, column=0, sticky='w')
        Button(history_frame, text=translate('open_location'), command=lambda dest=destination: os.startfile(dest), style='TButton').grid(row=idx, column=1, padx=5, pady=5)

# Função para limpar todo o histórico
def clear_history():
    global history
    history = []
    save_history(history)
    update_history_list()

# Função para mudar o idioma
def change_language(lang):
    global current_language
    current_language = lang
    config['language'] = lang
    save_config(config)
    update_ui_language()

# Função para atualizar a UI com o idioma selecionado
def update_ui_language():
    notebook.tab(0, text=translate('download'))
    notebook.tab(1, text=translate('history'))
    youtube_link_label.config(text=translate('youtube_link'))
    paste_link_button.config(text=translate('paste_link'))
    fetch_info_button.config(text=translate('fetch_info'))
    download_path_label.config(text=translate('download_path'))
    choose_path_button.config(text=translate('choose_path'))
    download_button.config(text=translate('download'))
    clear_history_button.config(text=translate('clear_history'))

# Criação da GUI
root = tk.Tk()
root.title("YouTube Downloader")

style = Style(root)
style.theme_use('clam')
style.configure('TButton', font=('Roboto', 12), padding=10, relief="flat")
style.configure('Accent.TButton', background='#00aaff', foreground='white')
style.configure('TLabel', font=('Roboto', 12))
style.configure('TEntry', font=('Roboto', 12), padding=5, relief="flat")
style.configure('TFrame', background='white', padding=10)

root.configure(bg='#f0f0f0')

notebook = ttk.Notebook(root)
notebook.pack(padx=10, pady=10, expand=True, fill='both')

# Aba de Download
download_tab = Frame(notebook, style='TFrame')
notebook.add(download_tab, text=translate('download'))

# Variáveis definidas aqui
url_var = tk.StringVar()
destination_var = tk.StringVar(value=config['destination'])
info_var = tk.StringVar()
stats_var = tk.StringVar()

# Campo de URL
youtube_link_label = Label(download_tab, text=translate('youtube_link'), anchor='w', background='white')
youtube_link_label.grid(row=0, column=0, padx=5, pady=5, sticky='w')
url_entry = Entry(download_tab, textvariable=url_var, width=40)
url_entry.grid(row=0, column=1, padx=5, pady=5)
paste_link_button = Button(download_tab, text=translate('paste_link'), command=paste_link, style='TButton')
paste_link_button.grid(row=0, column=2, padx=5, pady=5)

# Botão para buscar informações do vídeo
fetch_info_button = Button(download_tab, text=translate('fetch_info'), command=fetch_video_info, style='Accent.TButton')
fetch_info_button.grid(row=1, column=0, columnspan=3, padx=5, pady=5)

# Label para exibir informações do vídeo
Label(download_tab, textvariable=info_var, justify="left", background='white').grid(row=2, column=0, columnspan=3, padx=5, pady=5)

# Label para exibir thumbnail do vídeo
thumbnail_label = Label(download_tab, background='white')
thumbnail_label.grid(row=3, column=0, columnspan=3, padx=5, pady=5)

# Botão para escolher a pasta de destino
download_path_label = Label(download_tab, text=translate('download_path'), anchor='w', background='white')
download_path_label.grid(row=4, column=0, padx=5, pady=5, sticky='w')
choose_path_button = Button(download_tab, text=translate('choose_path'), command=choose_directory, style='TButton')
choose_path_button.grid(row=4, column=1, padx=5, pady=5, sticky='w')
Entry(download_tab, textvariable=destination_var, width=30).grid(row=4, column=2, padx=5, pady=5)

# Botão para iniciar/parar o download
download_button = Button(download_tab, text=translate('download'), command=download, style='Accent.TButton')
download_button.grid(row=5, column=0, columnspan=3, padx=5, pady=10)

# Barra de progresso
progress_var = tk.DoubleVar()
progress_bar = Progressbar(download_tab, variable=progress_var, maximum=100)
progress_bar.grid(row=6, column=0, columnspan=3, padx=5, pady=10, sticky='ew')

# Campo de estatísticas
Label(download_tab, textvariable=stats_var, background='white').grid(row=7, column=0, columnspan=3, padx=5, pady=10)

# Botão para abrir o local do arquivo
open_location_button = Button(download_tab, text=translate('open_location'), command=open_download_location, style='Accent.TButton')
open_location_button.grid_remove()  # Hide by default

# Aba de Histórico
history_tab = Frame(notebook, style='TFrame')
notebook.add(history_tab, text=translate('history'))

# Frame para lista de histórico
history_frame = Frame(history_tab, style='TFrame')
history_frame.pack(padx=10, pady=10, expand=True, fill='both')

# Botão para limpar todo o histórico
clear_history_button = Button(history_tab, text=translate('clear_history'), command=clear_history, style='Accent.TButton')
clear_history_button.pack(pady=10)

# Atualiza a lista de histórico na inicialização
update_history_list()

# Menu de idiomas
menubar = tk.Menu(root)
language_menu = tk.Menu(menubar, tearoff=0)
language_menu.add_command(label="English", command=lambda: change_language('en'))
language_menu.add_command(label="Português (Brasil)", command=lambda: change_language('pt'))
language_menu.add_command(label="Español", command=lambda: change_language('es'))
menubar.add_cascade(label="Language", menu=language_menu)
root.config(menu=menubar)

# Atualiza a UI com o idioma inicial
update_ui_language()

root.mainloop()