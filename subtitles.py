import threading
import queue
import json
import time
import numpy as np
from vosk import KaldiRecognizer
import pyaudiowpatch as pyaudio

class SubtitlesEngine:
    def __init__(self, model, callback=None, level_callback=None, error_callback=None):
        self.model = model
        self.callback = callback
        self.level_callback = level_callback
        self.error_callback = error_callback
        self.audio_queue = queue.Queue()
        self.is_running = False
        self.recognizer = None
        self.audio_stream = None
        self.p = None
        self.current_device = None
        self.thread = None
        self.last_text = ""

    def load_model(self):
        try:
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
            return True
        except Exception as e:
            self._handle_error(f"Ошибка загрузки модели: {e}")
            return False

    def set_device(self, device_index):
        self.current_device = None
        p = pyaudio.PyAudio()
        try:
            dev = p.get_device_info_by_index(device_index)
            if dev['maxInputChannels'] > 0:
                sample_rate = int(dev['defaultSampleRate'])
                self.current_device = (device_index,
                                       dev['maxInputChannels'],
                                       sample_rate)
        except Exception as e:
            self._handle_error(f"Ошибка установки устройства: {e}")
        finally:
            p.terminate()
        return self.current_device is not None

    def get_loopback_devices(self):
        """Возвращает список доступных loopback (WASAPI) устройств в формате (index, name)."""
        loopback_devices = []
        p = pyaudio.PyAudio()
        try:
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                wasapi_index = wasapi_info.get('index')
            except OSError:
                return []

            num_devices = p.get_device_count()
            for dev_idx in range(num_devices):
                try:
                    device_info = p.get_device_info_by_index(dev_idx)
                    
                    if (device_info.get('hostApi') == wasapi_index and 
                            device_info.get('isLoopbackDevice', False)):
                        
                        # Возвращаем кортеж (индекс, имя), который ожидает main.py
                        loopback_devices.append((dev_idx, device_info.get('name')))
                except Exception:
                    continue
                    
        except Exception as e:
            self._handle_error(f"Ошибка получения loopback устройств: {e}")
        finally:
            p.terminate()
        return loopback_devices


    def audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_running:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def convert_to_mono_16k(self, audio_bytes, input_channels, input_rate):
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        if self.level_callback:
            rms = np.sqrt(np.mean(audio.astype(np.float32)**2))
            level = min(100, int(rms / 32768 * 100))
            self.level_callback(level)
        if input_channels > 1:
            audio = audio.reshape(-1, input_channels).mean(axis=1).astype(np.int16)
        if input_rate != 16000:
            old_len = len(audio)
            new_len = int(old_len * 16000 / input_rate)
            indices = np.linspace(0, old_len - 1, new_len)
            audio = np.interp(indices, np.arange(old_len), audio).astype(np.int16)
        return audio.tobytes()

    def start(self):
        if self.is_running or self.audio_stream:
            return True
        if not self.recognizer and not self.load_model():
            return False
        if not self.current_device:
            if not self.set_device(None):
                return False
        self.is_running = True
        self.p = pyaudio.PyAudio()
        try:
            dev_idx, channels, rate = self.current_device[0], self.current_device[1], self.current_device[2]
            
            user_buffer = 512
            try:
                import json, os
                if os.path.exists("settings.json"):
                    with open("settings.json", "r", encoding="utf-8") as f:
                        user_buffer = json.load(f).get("subtitles", {}).get("buffer_size", 512)
            except:
                user_buffer = 512

            self.audio_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=user_buffer,
                stream_callback=self.audio_callback
            )
            self.audio_stream.start_stream()
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
            self.thread = threading.Thread(target=self.process_loop, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            self._handle_error(f"Не удалось запустить захват звука: {e}")
            self.stop()
            return False

    def process_loop(self):
        history = []
        max_history_lines = 1
        channels, rate = self.current_device[1], self.current_device[2]
        last_sent_display = ""

        q_timeout = 0.05
        v_timeout = 0.4
        try:
            import json, os
            if os.path.exists("settings.json"):
                with open("settings.json", "r", encoding="utf-8") as f:
                    sub_cfg = json.load(f).get("subtitles", {})
                    q_timeout = sub_cfg.get("queue_timeout", 0.05)
                    v_timeout = sub_cfg.get("vosk_timeout", 0.4)
        except:
            pass

        if hasattr(self, 'recognizer') and self.recognizer:
            endpoint_cfg = (
                f'{{"endpointing": {{'
                f'"rule1": {{"grace_period": {v_timeout}}},'
                f'"rule2": {{"grace_period": {v_timeout}}},'
                f'"rule3": {{"grace_period": {v_timeout}}}'
                f'}}}}'
            )
            try:
                self.recognizer.SetProperty("config", endpoint_cfg)
            except:
                pass

        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=q_timeout)
                converted = self.convert_to_mono_16k(data, channels, rate)
                
                if self.recognizer.AcceptWaveform(converted):
                    res = json.loads(self.recognizer.Result())
                    text = res.get("text", "").strip()
                    if text:
                        history.append(text)
                        if len(history) > max_history_lines:
                            history.pop(0)
                        
                        full_display = "\n".join(history)
                        if full_display != last_sent_display and self.callback:
                            self.callback(full_display, False)
                            last_sent_display = full_display
                else:
                    partial = json.loads(self.recognizer.PartialResult())
                    part_text = partial.get("partial", "").strip()
                    
                    current_lines = list(history)
                    if part_text:
                        current_lines.append(part_text)
                    
                    if len(current_lines) > 2:
                        current_lines.pop(0)
                        
                    if current_lines:
                        temp_display = "\n".join(current_lines)
                        if temp_display != last_sent_display and self.callback:
                            self.callback(temp_display, True)
                            last_sent_display = temp_display

            except queue.Empty:
                continue
            except Exception as e:
                self._handle_error(f"Ошибка в цикле обработки текста: {e}")

    def stop(self):
        self.is_running = False
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

    def _handle_error(self, message):
        if self.error_callback:
            self.error_callback(message)
        else:
            print(message)
