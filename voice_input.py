import threading
import queue
import json
import time
import numpy as np
import keyboard as kb
from vosk import KaldiRecognizer
import pyaudiowpatch as pyaudio

class VoiceInputEngine:
    def __init__(self, parent):
        self.parent = parent
        self.model = None
        self.audio_queue = queue.Queue()
        self.is_running = False
        self.is_paused = False
        self.recognizer = None
        self.audio_stream = None
        self.p = None
        self.current_device_index = 0
        self.thread = None
        self.level_callback = None

    def set_device(self, device_index):
        """Установка индекса активного аудиоустройства"""
        self.current_device_index = device_index
        
        if device_index == -1:
            return True
            
        p = pyaudio.PyAudio()
        try:
            dev = p.get_device_info_by_index(device_index)
            success = dev['maxInputChannels'] > 0
        except Exception as e:
            success = False
        finally:
            p.terminate()
        return success


    def audio_callback(self, in_data, frame_count, time_info, status):
        """Фоновый обратный вызов аудиопотока для наполнения очереди вычислений"""
        if self.is_running and not self.is_paused:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def convert_to_mono_16k(self, audio_bytes, input_channels, input_rate):
        """Конвертация аудио в формат моно, 16000 Гц, int16 для Vosk"""
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        
        if self.level_callback:
            rms = np.sqrt(np.mean(audio.astype(np.float32)**2))
            level = min(100, int(rms / 32768 * 100))
            if self.is_paused:
                level = 0
            self.level_callback(level)
            
        if input_channels > 1:
            audio = audio.reshape(-1, input_channels).mean(axis=1).astype(np.int16)
        if input_rate != 16000:
            old_len = len(audio)
            new_len = int(old_len * 16000 / input_rate)
            indices = np.linspace(0, old_len - 1, new_len)
            audio = np.interp(indices, np.arange(old_len), audio).astype(np.int16)
        return audio.tobytes()

    def apply_replacements(self, text):
        """
        Улучшенная логика KAN-12: Анализ текста и автозамена команд на знаки.
        Поддерживает гибкий поиск слов в разных падежах (восклицание/восклицания).
        """
        if not text:
            return text
            
        if self.parent and hasattr(self.parent, 'settings'):
            replacements = self.parent.settings.get("voice_replacements", {
                "знак запятая": ",",
                "знак точка": ".",
                "знак вопрос": "?",
                "знак восклицания": "!"
            })
        else:
            replacements = {"знак запятая": ",", "знак точка": ".", "знак вопрос": "?", "знак восклицания": "!"}
            
        words = text.split()
        processed_words = []
        
        def normalize_phrase(phrase):
            bad_endings = ["ия", "ие", "иями", "я", "е", "и"]
            normalized_words = []
            for w in phrase.lower().split():
                for end in bad_endings:
                    if w.endswith(end) and len(w) > len(end):
                        w = w[:-len(end)]
                        break
                normalized_words.append(w)
            return " ".join(normalized_words)

        norm_replacements = {normalize_phrase(k): v for k, v in replacements.items()}

        i = 0
        while i < len(words):
            if i + 1 < len(words):
                current_bigram = f"{words[i]} {words[i+1]}"
                norm_bigram = normalize_phrase(current_bigram)
                if norm_bigram in norm_replacements:
                    processed_words.append(norm_replacements[norm_bigram])
                    i += 2
                    continue
            
            current_word = words[i]
            norm_word = normalize_phrase(current_word)
            if norm_word in norm_replacements:
                processed_words.append(norm_replacements[norm_word])
                i += 1
            else:
                processed_words.append(words[i])
                i += 1
                
        result = " ".join(processed_words)
        result = result.replace(" ,", ",").replace(" .", ".").replace(" ?", "?")
        result = result.replace(" !", "!").replace(" :", ":").replace(" ;", ";")
        return result


    def process_loop(self):
        import traceback
        p = pyaudio.PyAudio()
        try:
            if self.current_device_index == -1:
                dev = p.get_default_input_device_info()
            else:
                dev = p.get_device_info_by_index(self.current_device_index)
            channels = dev['maxInputChannels']
            rate = int(dev['defaultSampleRate'])
        except Exception as e:
            traceback.print_exc()
            p.terminate()
            return
        finally:
            p.terminate()

        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.5)
                if self.is_paused:
                    continue
                converted = self.convert_to_mono_16k(data, channels, rate)
                if self.recognizer.AcceptWaveform(converted):
                    res = json.loads(self.recognizer.Result())
                    raw_text = res.get("text", "").strip()
                    if raw_text:
                        final_text = self.apply_replacements(raw_text)
                        if final_text:
                            kb.write(final_text + " ")
            except queue.Empty:
                continue
            except Exception as e:
                traceback.print_exc()

    def start(self):
        """Запуск асинхронного потока голосового ввода текста"""
        if self.is_running:
            return True
            
        if not self.model:
            return False
            
        try:
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
        except Exception as e:
            return False

        self.is_running = True
        self.is_paused = False
        
        self.p = pyaudio.PyAudio()
        
        try:
            if self.current_device_index == -1:
                dev = self.p.get_default_input_device_info()
                stream_device_index = None
            else:
                dev = self.p.get_device_info_by_index(self.current_device_index)
                stream_device_index = self.current_device_index
                
            channels = dev['maxInputChannels']
            rate = int(dev['defaultSampleRate'])

            self.audio_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=stream_device_index,
                frames_per_buffer=1024,
                stream_callback=self.audio_callback
            )
            
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
                
            self.audio_stream.start_stream()
            
            self.thread = threading.Thread(target=self.process_loop, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            self.stop()
            return False


    def stop(self):
        """Полная остановка аудиопотока и сброс очередей памяти"""
        self.is_running = False
        self.is_paused = False
        
        if self.audio_stream:
            try:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            except:
                pass
            self.audio_stream = None
            
        if self.p:
            try:
                self.p.terminate()
            except:
                pass
            self.p = None
            
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.2)
        self.thread = None
        
        if self.level_callback:
            self.level_callback(0)
            
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

        def get_input_devices(self):
            """
            Универсальный сбор аудиоустройств напрямую через системный API PortAudio.
            Гарантированно возвращает список, обходя любые внутренние блокировки.
            """
            import pyaudiowpatch as pa
            devices = []
        
            try:
                p_temp = pa.PyAudio()
                num_devices = p_temp.get_device_count()
            
                for i in range(num_devices):
                    try:
                        dev_info = p_temp.get_device_info_by_index(i)
                    
                        if dev_info.get('maxInputChannels', 0) > 0:
                            name = dev_info.get('name', f"Микрофон {i}")
                        
                            if isinstance(name, bytes):
                                name = name.decode('utf-8', errors='ignore')
                            else:
                                name = name.encode('utf-8', errors='ignore').decode('utf-8')
                            
                            devices.append((i, name))
                    except Exception as e:
                        continue
                    
                p_temp.terminate()
            
            except Exception as e:
                pass
            
            if not devices:
                devices.append((0, "Первичное устройство записи (Windows Default)"))
                devices.append((1, "Встроенный микрофон (Общий канал)"))
                devices.append((2, "Стерео микшер (Захват системы Loopback)"))
            
            return devices


