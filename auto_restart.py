import sys
import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class RestartBotHandler(FileSystemEventHandler):
   def __init__(self, script):
       self.script = script
       self.process = self.start_bot()

   def start_bot(self):
       return subprocess.Popen([sys.executable, self.script])

   def on_any_event(self, event):
       if event.src_path.endswith('.py'):
           print('Изменение в коде обнаружено. Перезапуск бота...')
           self.process.kill()
           self.process = self.start_bot()

if __name__ == '__main__':
   print("Запущен auto_restart.py")

   script_name = 'main_seo.py'  # Замените на имя вашего файла с ботом
   event_handler = RestartBotHandler(script=script_name)
   observer = Observer()
   observer.schedule(event_handler, path='.', recursive=True)
   observer.start()
   print('Запущен автообновляемый бот. Наблюдение за изменениями кода...')
   try:
       while True:
           time.sleep(1)
   except KeyboardInterrupt:
       observer.stop()
   observer.join()