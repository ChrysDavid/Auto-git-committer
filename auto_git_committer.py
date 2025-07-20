import os
import subprocess
import schedule
import time
import json
from datetime import datetime
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sys
from enum import Enum
import queue

class CommitStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class StatusUpdate:
    def __init__(self, repo_name, status, message="", timestamp=None):
        self.repo_name = repo_name
        self.status = status
        self.message = message
        self.timestamp = timestamp or datetime.now()



def get_base_dir():
    if getattr(sys, 'frozen', False):  # Exécuté via PyInstaller (.exe)
        return os.path.dirname(sys.executable)
    else:  # Exécuté en mode .py normal
        return os.path.dirname(os.path.abspath(__file__))

class AutoGitCommitter:
    def __init__(self, status_callback=None):
        self.script_dir = get_base_dir()
        self.config_file = os.path.join(self.script_dir, "config.json")
        self.log_file = os.path.join(self.script_dir, "git_commits.log")
        self.status_callback = status_callback
        
        # Configuration du logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Variables pour le contrôle du thread
        self.running = False
        self.worker_thread = None
        
        # Charger ou créer la configuration
        self.config = self.load_config()

        
    
    def notify_status(self, repo_name, status, message=""):
        """Notifie le changement de statut à l'interface"""
        if self.status_callback:
            self.status_callback(StatusUpdate(repo_name, status, message))
    
    def load_config(self):
        """Charge la configuration depuis le fichier JSON"""
        default_config = {
            "commit_times": ["09:00", "18:00"],
            "commit_message": "Auto commit - {date}",
            "excluded_folders": [".git", "__pycache__", ".vscode", "node_modules"],
            "excluded_files": [".exe", ".log", "config.json"],
            "auto_push": True
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
            except Exception as e:
                self.logger.error(f"Erreur lors du chargement de la config: {e}")
                return default_config
        else:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            self.logger.info(f"Fichier de configuration créé: {self.config_file}")
            return default_config
    
    def save_config(self):
        """Sauvegarde la configuration dans le fichier JSON"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"Erreur lors de la sauvegarde: {e}")
            return False
    
    def is_git_repository(self, path):
        """Vérifie si le dossier est un dépôt Git"""
        return os.path.exists(os.path.join(path, '.git'))
    
    def has_changes(self, repo_path):
        """Vérifie s'il y a des changements dans le dépôt"""
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return bool(result.stdout.strip())
        except subprocess.CalledProcessError:
            return False
    
    def run_git_command(self, command, repo_path):
        """Exécute une commande Git dans le dépôt spécifié"""
        try:
            result = subprocess.run(
                command,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr
    
    def commit_repository(self, repo_path):
        """Effectue un commit complet pour un dépôt"""
        repo_name = os.path.basename(repo_path)
        self.logger.info(f"Traitement du dépôt: {repo_name}")
        
        # Notification du début du traitement
        self.notify_status(repo_name, CommitStatus.IN_PROGRESS, "Vérification des changements...")
        
        if not self.has_changes(repo_path):
            self.logger.info(f"Aucun changement détecté dans {repo_name}")
            self.notify_status(repo_name, CommitStatus.SKIPPED, "Aucun changement détecté")
            return True
        
        # Ajout des fichiers
        self.notify_status(repo_name, CommitStatus.IN_PROGRESS, "Ajout des fichiers...")
        success, output = self.run_git_command(['git', 'add', '.'], repo_path)
        if not success:
            self.logger.error(f"Erreur lors de l'ajout des fichiers dans {repo_name}: {output}")
            self.notify_status(repo_name, CommitStatus.FAILED, f"Erreur lors de l'ajout: {output[:50]}...")
            return False
        
        # Commit
        self.notify_status(repo_name, CommitStatus.IN_PROGRESS, "Création du commit...")
        commit_message = self.config["commit_message"].format(
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        success, output = self.run_git_command(
            ['git', 'commit', '-m', commit_message],
            repo_path
        )
        if not success:
            self.logger.error(f"Erreur lors du commit dans {repo_name}: {output}")
            self.notify_status(repo_name, CommitStatus.FAILED, f"Erreur de commit: {output[:50]}...")
            return False
        
        self.logger.info(f"Commit réalisé dans {repo_name}")
        
        # Push si activé
        if self.config["auto_push"]:
            self.notify_status(repo_name, CommitStatus.IN_PROGRESS, "Push vers le dépôt distant...")
            success, output = self.run_git_command(['git', 'push'], repo_path)
            if not success:
                self.logger.warning(f"Erreur lors du push dans {repo_name}: {output}")
                self.notify_status(repo_name, CommitStatus.FAILED, f"Erreur de push: {output[:50]}...")
                return False
            self.logger.info(f"Push réalisé avec succès pour {repo_name}")
            self.notify_status(repo_name, CommitStatus.SUCCESS, "Commit et push réalisés avec succès")
        else:
            self.notify_status(repo_name, CommitStatus.SUCCESS, "Commit réalisé avec succès")
        
        return True
    
    def find_git_repositories(self):
        """Trouve tous les dépôts Git dans le dossier courant"""
        repositories = []
        
        for item in os.listdir(self.script_dir):
            item_path = os.path.join(self.script_dir, item)
            
            if (item in self.config["excluded_folders"] or 
                any(item.endswith(ext) for ext in self.config["excluded_files"])):
                continue
            
            if os.path.isdir(item_path) and self.is_git_repository(item_path):
                repositories.append(item_path)
        
        return repositories
    
    def commit_all_repositories(self):
        """Effectue les commits pour tous les dépôts trouvés"""
        self.logger.info("=== Début du processus de commit automatique ===")
        
        repositories = self.find_git_repositories()
        
        if not repositories:
            self.logger.info("Aucun dépôt Git trouvé dans le dossier")
            return
        
        self.logger.info(f"Dépôts trouvés: {[os.path.basename(repo) for repo in repositories]}")
        
        # Initialiser le statut des repos
        for repo_path in repositories:
            repo_name = os.path.basename(repo_path)
            self.notify_status(repo_name, CommitStatus.PENDING, "En attente de traitement")
        
        success_count = 0
        for repo_path in repositories:
            if self.commit_repository(repo_path):
                success_count += 1
        
        self.logger.info(f"=== Fin du processus: {success_count}/{len(repositories)} dépôts traités avec succès ===")
    
    def setup_schedule(self):
        """Configure la planification des commits"""
        schedule.clear()
        for commit_time in self.config["commit_times"]:
            schedule.every().day.at(commit_time).do(self.commit_all_repositories)
            self.logger.info(f"Commit programmé à {commit_time}")
    
    def worker_loop(self):
        """Boucle de travail en arrière-plan"""
        self.setup_schedule()
        while self.running:
            schedule.run_pending()
            time.sleep(60)
    
    def start_worker(self):
        """Démarre le processus en arrière-plan"""
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self.worker_loop, daemon=True)
            self.worker_thread.start()
            self.logger.info("Service de commit automatique démarré")
    
    def stop_worker(self):
        """Arrête le processus en arrière-plan"""
        if self.running:
            self.running = False
            self.logger.info("Service de commit automatique arrêté")

class StatusMonitor:
    def __init__(self, parent):
        self.parent = parent
        self.status_queue = queue.Queue()
        
        # Dictionnaire pour stocker les statuts des repos
        self.repo_statuses = {}
        
        self.setup_ui()
        
        # Vérifier les mises à jour de statut
        self.check_status_updates()
    
    def setup_ui(self):
        """Configure l'interface du moniteur de statut"""
        # Frame principal
        self.frame = ttk.LabelFrame(self.parent, text="📊 Moniteur de Statut des Commits")
        self.frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Canvas avec scrollbar pour les statuts
        canvas_frame = ttk.Frame(self.frame)
        canvas_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        self.canvas = tk.Canvas(canvas_frame, height=200, bg='white')
        scrollbar = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Frame pour les widgets de statut
        self.status_widgets = {}
        
        # Message initial
        initial_label = ttk.Label(self.scrollable_frame, text="🔄 En attente du premier commit...", 
                                 font=('Arial', 10, 'italic'))
        initial_label.pack(pady=20)
        
        # Statistiques globales
        stats_frame = ttk.Frame(self.frame)
        stats_frame.pack(fill='x', padx=5, pady=5)
        
        self.stats_label = ttk.Label(stats_frame, text="📈 Statistiques: 0 dépôts", 
                                   font=('Arial', 9, 'bold'))
        self.stats_label.pack(side='left')
        
        self.last_run_label = ttk.Label(stats_frame, text="⏰ Dernier run: Jamais", 
                                      font=('Arial', 9))
        self.last_run_label.pack(side='right')
    
    def get_status_icon(self, status):
        """Retourne l'icône correspondant au statut"""
        icons = {
            CommitStatus.PENDING: "⏳",
            CommitStatus.IN_PROGRESS: "🔄",
            CommitStatus.SUCCESS: "✅",
            CommitStatus.FAILED: "❌",
            CommitStatus.SKIPPED: "⏭️"
        }
        return icons.get(status, "❓")
    
    def get_status_color(self, status):
        """Retourne la couleur correspondant au statut"""
        colors = {
            CommitStatus.PENDING: "#FFA500",  # Orange
            CommitStatus.IN_PROGRESS: "#1E90FF",  # Bleu
            CommitStatus.SUCCESS: "#32CD32",  # Vert
            CommitStatus.FAILED: "#FF4500",  # Rouge
            CommitStatus.SKIPPED: "#696969"  # Gris
        }
        return colors.get(status, "#000000")
    
    def add_status_update(self, update):
        """Ajoute une mise à jour de statut à la queue"""
        self.status_queue.put(update)
    
    def check_status_updates(self):
        """Vérifie et traite les mises à jour de statut"""
        try:
            while True:
                update = self.status_queue.get_nowait()
                self.update_repo_status(update)
        except queue.Empty:
            pass
        
        # Programmer la prochaine vérification
        self.parent.after(100, self.check_status_updates)
    
    def update_repo_status(self, update):
        """Met à jour le statut d'un dépôt"""
        repo_name = update.repo_name
        
        # Mettre à jour le dictionnaire de statut
        self.repo_statuses[repo_name] = update
        
        # Supprimer le message initial si nécessaire
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, ttk.Label) and "En attente du premier commit" in widget.cget("text"):
                widget.destroy()
        
        # Créer ou mettre à jour le widget de statut pour ce repo
        if repo_name not in self.status_widgets:
            self.create_status_widget(repo_name)
        
        self.update_status_widget(repo_name, update)
        self.update_global_stats()
    
    def create_status_widget(self, repo_name):
        """Crée un nouveau widget de statut pour un dépôt"""
        frame = ttk.Frame(self.scrollable_frame, relief='solid', borderwidth=1)
        frame.pack(fill='x', padx=5, pady=2)
        
        # Ligne principale avec icône, nom et statut
        main_frame = ttk.Frame(frame)
        main_frame.pack(fill='x', padx=5, pady=3)
        
        icon_label = ttk.Label(main_frame, text="⏳", font=('Arial', 14))
        icon_label.pack(side='left', padx=(0, 5))
        
        name_label = ttk.Label(main_frame, text=f"📁 {repo_name}", font=('Arial', 10, 'bold'))
        name_label.pack(side='left')
        
        status_label = ttk.Label(main_frame, text="En attente...", font=('Arial', 9))
        status_label.pack(side='right')
        
        # Ligne de détails
        detail_frame = ttk.Frame(frame)
        detail_frame.pack(fill='x', padx=5, pady=(0, 3))
        
        message_label = ttk.Label(detail_frame, text="", font=('Arial', 8), foreground='gray')
        message_label.pack(side='left')
        
        time_label = ttk.Label(detail_frame, text="", font=('Arial', 8), foreground='gray')
        time_label.pack(side='right')
        
        # Barre de progression (pour les statuts en cours)
        progress_bar = ttk.Progressbar(frame, mode='indeterminate')
        
        self.status_widgets[repo_name] = {
            'frame': frame,
            'icon': icon_label,
            'name': name_label,
            'status': status_label,
            'message': message_label,
            'time': time_label,
            'progress': progress_bar
        }
    
    def update_status_widget(self, repo_name, update):
        """Met à jour un widget de statut existant"""
        if repo_name not in self.status_widgets:
            return
        
        widgets = self.status_widgets[repo_name]
        
        # Mettre à jour l'icône et la couleur
        icon = self.get_status_icon(update.status)
        color = self.get_status_color(update.status)
        
        widgets['icon'].config(text=icon)
        widgets['status'].config(text=update.status.value.replace('_', ' ').title(), foreground=color)
        
        # Mettre à jour le message
        widgets['message'].config(text=update.message if update.message else "")
        
        # Mettre à jour l'horodatage
        time_str = update.timestamp.strftime("%H:%M:%S")
        widgets['time'].config(text=time_str)
        
        # Gérer la barre de progression
        if update.status == CommitStatus.IN_PROGRESS:
            widgets['progress'].pack(fill='x', padx=5, pady=(0, 3))
            widgets['progress'].start(10)
        else:
            widgets['progress'].stop()
            widgets['progress'].pack_forget()
        
        # Faire défiler vers le bas
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)
    
    def update_global_stats(self):
        """Met à jour les statistiques globales"""
        total = len(self.repo_statuses)
        success = sum(1 for status in self.repo_statuses.values() if status.status == CommitStatus.SUCCESS)
        failed = sum(1 for status in self.repo_statuses.values() if status.status == CommitStatus.FAILED)
        in_progress = sum(1 for status in self.repo_statuses.values() if status.status == CommitStatus.IN_PROGRESS)
        
        stats_text = f"📈 Total: {total} | ✅ Succès: {success} | ❌ Échecs: {failed}"
        if in_progress > 0:
            stats_text += f" | 🔄 En cours: {in_progress}"
        
        self.stats_label.config(text=stats_text)
        
        # Mettre à jour l'heure du dernier run
        if self.repo_statuses:
            latest_time = max(status.timestamp for status in self.repo_statuses.values())
            self.last_run_label.config(text=f"⏰ Dernier run: {latest_time.strftime('%H:%M:%S')}")
    
    def clear_status(self):
        """Efface tous les statuts"""
        for widgets in self.status_widgets.values():
            widgets['frame'].destroy()
        self.status_widgets.clear()
        self.repo_statuses.clear()
        
        # Remettre le message initial
        initial_label = ttk.Label(self.scrollable_frame, text="🔄 En attente du premier commit...", 
                                 font=('Arial', 10, 'italic'))
        initial_label.pack(pady=20)
        
        self.stats_label.config(text="📈 Statistiques: 0 dépôts")
        self.last_run_label.config(text="⏰ Dernier run: Jamais")

class GitCommitterGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Auto Git Committer - Configuration")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)
        
        # Style
        style = ttk.Style()
        style.theme_use('vista')
        
        # Initialiser le committer avec callback
        self.committer = AutoGitCommitter(status_callback=self.handle_status_update)
        
        self.setup_ui()
        self.load_config_to_ui()
        
        # Gestionnaire de fermeture
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def handle_status_update(self, update):
        """Gestionnaire des mises à jour de statut"""
        self.status_monitor.add_status_update(update)
    
    def setup_ui(self):
        """Configure l'interface utilisateur"""
        # Titre principal
        title_frame = ttk.Frame(self.root)
        title_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(title_frame, text="Auto Git Committer", 
                 font=('Arial', 16, 'bold')).pack()
        ttk.Label(title_frame, text="Configuration des commits automatiques", 
                 font=('Arial', 10)).pack()
        
        # Frame principal divisé en deux colonnes
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Colonne gauche - Configuration
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        # Notebook pour les onglets
        notebook = ttk.Notebook(left_frame)
        notebook.pack(fill='both', expand=True)
        
        # Onglet Configuration
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="⚙️ Configuration")
        self.setup_config_tab(config_frame)
        
        # Onglet Dépôts
        repos_frame = ttk.Frame(notebook)
        notebook.add(repos_frame, text="📁 Dépôts Git")
        self.setup_repos_tab(repos_frame)
        
        # Onglet Logs
        logs_frame = ttk.Frame(notebook)
        notebook.add(logs_frame, text="📝 Logs")
        self.setup_logs_tab(logs_frame)
        
        # Colonne droite - Moniteur de statut
        right_frame = ttk.Frame(main_frame, width=350)
        right_frame.pack(side='right', fill='both', padx=(5, 0))
        right_frame.pack_propagate(False)
        
        # Créer le moniteur de statut
        self.status_monitor = StatusMonitor(right_frame)
        
        # Boutons de contrôle
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(control_frame, text="💾 Sauvegarder Config", 
                  command=self.save_config).pack(side='left', padx=5)
        ttk.Button(control_frame, text="🔧 Test Commit Manuel", 
                  command=self.manual_commit).pack(side='left', padx=5)
        ttk.Button(control_frame, text="🗑️ Effacer Statuts", 
                  command=self.clear_status).pack(side='left', padx=5)
        
        self.start_button = ttk.Button(control_frame, text="▶️ Démarrer Service", 
                                      command=self.toggle_service)
        self.start_button.pack(side='right', padx=5)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("🔴 Service arrêté")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, 
                              relief='sunken', anchor='w')
        status_bar.pack(fill='x', side='bottom')
    
    def setup_config_tab(self, parent):
        """Configure l'onglet de configuration"""
        # Frame pour les heures
        time_frame = ttk.LabelFrame(parent, text="⏰ Heures de Commit")
        time_frame.pack(fill='x', padx=10, pady=5)
        
        # Liste des heures
        self.times_listbox = tk.Listbox(time_frame, height=4)
        self.times_listbox.pack(fill='x', padx=5, pady=5)
        
        # Contrôles pour ajouter/supprimer des heures
        time_controls = ttk.Frame(time_frame)
        time_controls.pack(fill='x', padx=5, pady=5)
        
        ttk.Label(time_controls, text="Nouvelle heure (HH:MM):").pack(side='left')
        self.time_entry = ttk.Entry(time_controls, width=10)
        self.time_entry.pack(side='left', padx=5)
        ttk.Button(time_controls, text="➕ Ajouter", 
                  command=self.add_time).pack(side='left', padx=2)
        ttk.Button(time_controls, text="➖ Supprimer", 
                  command=self.remove_time).pack(side='left', padx=2)
        
        # Frame pour le message de commit
        msg_frame = ttk.LabelFrame(parent, text="💬 Message de Commit")
        msg_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(msg_frame, text="Modèle de message ({date} sera remplacé par la date):").pack(anchor='w', padx=5, pady=2)
        self.msg_entry = ttk.Entry(msg_frame)
        self.msg_entry.pack(fill='x', padx=5, pady=5)
        
        # Options
        options_frame = ttk.LabelFrame(parent, text="⚙️ Options")
        options_frame.pack(fill='x', padx=10, pady=5)
        
        self.auto_push_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="🚀 Push automatique vers GitHub", 
                       variable=self.auto_push_var).pack(anchor='w', padx=5, pady=2)
    
    def setup_repos_tab(self, parent):
        """Configure l'onglet des dépôts"""
        ttk.Label(parent, text="📁 Dépôts Git détectés dans le dossier:").pack(anchor='w', padx=10, pady=5)
        
        self.repos_tree = ttk.Treeview(parent, columns=('Status', 'Dernière modification'), show='tree headings')
        self.repos_tree.heading('#0', text='Nom du dépôt')
        self.repos_tree.heading('Status', text='Status')
        self.repos_tree.heading('Dernière modification', text='Dernière modification')
        
        scrollbar = ttk.Scrollbar(parent, orient='vertical', command=self.repos_tree.yview)
        self.repos_tree.configure(yscrollcommand=scrollbar.set)
        
        self.repos_tree.pack(fill='both', expand=True, padx=10, pady=5)
        scrollbar.pack(side='right', fill='y')
        
        ttk.Button(parent, text="🔄 Actualiser la liste", 
                  command=self.refresh_repos).pack(pady=5)
    
    def setup_logs_tab(self, parent):
        """Configure l'onglet des logs"""
        ttk.Label(parent, text="📝 Logs du système:").pack(anchor='w', padx=10, pady=5)
        
        self.logs_text = scrolledtext.ScrolledText(parent, height=20)
        self.logs_text.pack(fill='both', expand=True, padx=10, pady=5)
        
        ttk.Button(parent, text="🔄 Actualiser les logs", 
                  command=self.refresh_logs).pack(pady=5)
    
    def load_config_to_ui(self):
        """Charge la configuration dans l'interface"""
        # Heures de commit
        self.times_listbox.delete(0, tk.END)
        for time_str in self.committer.config["commit_times"]:
            self.times_listbox.insert(tk.END, time_str)
        
        # Message de commit
        self.msg_entry.delete(0, tk.END)
        self.msg_entry.insert(0, self.committer.config["commit_message"])
        
        # Auto push
        self.auto_push_var.set(self.committer.config["auto_push"])
        
        # Actualiser la liste des dépôts
        self.refresh_repos()
        
        # Charger les logs
        self.refresh_logs()
    
    def add_time(self):
        """Ajoute une nouvelle heure de commit"""
        time_str = self.time_entry.get().strip()
        if not time_str:
            return
        
        # Validation du format HH:MM
        try:
            datetime.strptime(time_str, "%H:%M")
            if time_str not in self.committer.config["commit_times"]:
                self.committer.config["commit_times"].append(time_str)
                self.committer.config["commit_times"].sort()
                self.times_listbox.insert(tk.END, time_str)
                self.time_entry.delete(0, tk.END)
        except ValueError:
            messagebox.showerror("Erreur", "Format d'heure invalide. Utilisez HH:MM (ex: 09:30)")
    
    def remove_time(self):
        """Supprime l'heure sélectionnée"""
        selection = self.times_listbox.curselection()
        if selection:
            index = selection[0]
            time_str = self.times_listbox.get(index)
            self.committer.config["commit_times"].remove(time_str)
            self.times_listbox.delete(index)
    
    def save_config(self):
        """Sauvegarde la configuration"""
        # Mettre à jour la config avec les valeurs de l'interface
        self.committer.config["commit_message"] = self.msg_entry.get()
        self.committer.config["auto_push"] = self.auto_push_var.get()
        
        if self.committer.save_config():
            messagebox.showinfo("Succès", "💾 Configuration sauvegardée avec succès!")
            # Reconfigurer le planning si le service est actif
            if self.committer.running:
                self.committer.setup_schedule()
        else:
            messagebox.showerror("Erreur", "❌ Erreur lors de la sauvegarde de la configuration")
    
    def refresh_repos(self):
        """Actualise la liste des dépôts"""
        # Vider la liste
        for item in self.repos_tree.get_children():
            self.repos_tree.delete(item)
        
        # Ajouter les dépôts trouvés
        repositories = self.committer.find_git_repositories()
        for repo_path in repositories:
            repo_name = os.path.basename(repo_path)
            has_changes = self.committer.has_changes(repo_path)
            status = "🔄 Changements détectés" if has_changes else "✅ À jour"
            
            # Dernière modification
            try:
                mod_time = os.path.getmtime(repo_path)
                mod_date = datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M")
            except:
                mod_date = "❓ Inconnue"
            
            self.repos_tree.insert('', 'end', text=f"📁 {repo_name}", values=(status, mod_date))
    
    def refresh_logs(self):
        """Actualise les logs"""
        try:
            with open(self.committer.log_file, 'r', encoding='utf-8') as f:
                logs = f.read()
            self.logs_text.delete('1.0', tk.END)
            self.logs_text.insert('1.0', logs)
            self.logs_text.see(tk.END)
        except FileNotFoundError:
            self.logs_text.delete('1.0', tk.END)
            self.logs_text.insert('1.0', "📝 Aucun fichier de log trouvé.")
    
    def manual_commit(self):
        """Effectue un commit manuel"""
        # Effacer les anciens statuts avant de commencer
        self.status_monitor.clear_status()
        
        # Démarrer le commit dans un thread séparé pour ne pas bloquer l'UI
        thread = threading.Thread(target=self._manual_commit_worker, daemon=True)
        thread.start()
    
    def _manual_commit_worker(self):
        """Worker pour le commit manuel"""
        self.committer.commit_all_repositories()
        # Actualiser l'interface dans le thread principal
        self.root.after(0, self._post_manual_commit)
    
    def _post_manual_commit(self):
        """Actions post-commit manuel"""
        self.refresh_repos()
        self.refresh_logs()
        messagebox.showinfo("Terminé", "✅ Commit manuel effectué. Consultez les statuts et logs pour les détails.")
    
    def clear_status(self):
        """Efface tous les statuts du moniteur"""
        self.status_monitor.clear_status()
        messagebox.showinfo("Information", "🗑️ Statuts effacés.")
    
    def toggle_service(self):
        """Active/désactive le service"""
        if self.committer.running:
            self.committer.stop_worker()
            self.start_button.config(text="▶️ Démarrer Service")
            self.status_var.set("🔴 Service arrêté")
        else:
            if not self.committer.config["commit_times"]:
                messagebox.showwarning("Attention", "⚠️ Aucune heure de commit configurée!")
                return
            
            self.committer.start_worker()
            self.start_button.config(text="⏸️ Arrêter Service")
            times_str = ", ".join(self.committer.config["commit_times"])
            self.status_var.set(f"🟢 Service actif - Prochains commits: {times_str}")
    
    def on_closing(self):
        """Gestionnaire de fermeture de l'application"""
        if self.committer.running:
            if messagebox.askokcancel("Fermeture", 
                                    "⚠️ Le service est actif. Voulez-vous vraiment fermer l'application?"):
                self.committer.stop_worker()
                self.root.destroy()
        else:
            self.root.destroy()
    
    def run(self):
        """Lance l'interface graphique"""
        self.root.mainloop()

if __name__ == "__main__":
    # Vérifier si on lance en mode console ou GUI
    if len(sys.argv) > 1 and sys.argv[1] == "--console":
        # Mode console pour exécution en arrière-plan
        committer = AutoGitCommitter()
        committer.start_worker()
        try:
            print("🚀 Auto Git Committer démarré en mode console")
            print("📊 Service de commit automatique actif...")
            print("⏹️  Appuyez sur Ctrl+C pour arrêter")
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\n⏹️  Arrêt du service...")
            committer.stop_worker()
            print("✅ Service arrêté.")
    else:
        # Mode GUI
        app = GitCommitterGUI()
        app.run()