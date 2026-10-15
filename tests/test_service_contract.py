"""Thirty turns through real HTTP adapters against local test services (no AI weights)."""
import io
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import unittest
import wave

from studio import app
from tests import test_behavior as fixtures


class ServiceContractTests(unittest.TestCase):
    def test_thirty_llm_tts_turns_keep_semantics_and_speech_lifecycle(self):
        fixture=fixtures.BehaviorPlanningTests("test_real_timeline_names_get_seed_tags");fixture.setUp()
        root=fixture.synthetic.folder.parent
        old=(app.DATA,app.GEN,app.SETTINGS_FILE,app.MANIFEST_FILE,app.DB_FILE,app.STATE,app.RUNTIME)
        counts={"llm":0,"tts":0}
        audio=io.BytesIO()
        with wave.open(audio,"wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
            wav.writeframes(b"\0\0"*1600)
        wav_bytes=audio.getvalue()

        class Service(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                obj=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path=="/v1/chat/completions":
                    counts["llm"]+=1
                    self.assert_contract(obj)
                    intent={"speech":"嗯，我知道了。","emotion":"happy","action_tag":"nod","intensity":.5,"scene":""}
                    content=json.dumps({"choices":[{"message":{"content":json.dumps(intent,ensure_ascii=False)}}]}).encode()
                    kind="application/json"
                elif self.path=="/tts":
                    counts["tts"]+=1
                    if obj["ref_audio_path"]!="test-reference.wav":raise ValueError("reference lost")
                    content=wav_bytes;kind="audio/wav"
                else:self.send_error(404);return
                self.send_response(200);self.send_header("Content-Type",kind)
                self.send_header("Content-Length",str(len(content)));self.end_headers();self.wfile.write(content)
            def assert_contract(self,obj):
                if obj["model"]!="contract-test" or not obj["messages"]:raise ValueError("invalid adapter payload")

        server=ThreadingHTTPServer(("127.0.0.1",0),Service)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            app.DATA=root/"service_qa";app.GEN=app.DATA/"generated"
            app.SETTINGS_FILE=app.DATA/"settings.json";app.MANIFEST_FILE=app.DATA/"manifest.json"
            app.DB_FILE=app.DATA/"history.sqlite3";app.init()
            app.RUNTIME=app.behavior_runtime.BehaviorRuntime()
            url=f"http://127.0.0.1:{server.server_port}"
            app.STATE["settings"].update(assets_dir=str(root),character_model="kan_0",llm_mode="openai",
                llm_url=url+"/v1",llm_model="contract-test",tts_enabled=True,
                tts_url=url+"/tts",tts_ref_audio="test-reference.wav")
            suppressed=0
            for index in range(30):
                result=app.chat_response("测试对话 "+str(index))
                self.assertEqual(result["source"],"openai-compatible")
                self.assertEqual(result["behavior"]["expression"]["label"],"笑顔Ａ")
                suppressed+=result["behavior"]["runtime_decision"]=="cooldown_suppressed"
                self.assertEqual(app.synthesize(result["speech"])[:4],b"RIFF")
                started=app.runtime_event("speech_start")
                self.assertEqual(started["phase"],"speaking")
                ended=app.runtime_event("speech_end")
                self.assertEqual(ended["emotion"],"happy")
            # Identical text and voice settings reuse the local WAV cache.
            self.assertEqual(counts,{"llm":30,"tts":1})
            self.assertGreater(suppressed,20)
        finally:
            server.shutdown();server.server_close()
            (app.DATA,app.GEN,app.SETTINGS_FILE,app.MANIFEST_FILE,app.DB_FILE,app.STATE,app.RUNTIME)=old
            fixture.tearDown()


if __name__=="__main__":unittest.main()
