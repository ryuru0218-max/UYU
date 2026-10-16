import os
import re
import io
import math
import random
import string
import base64
import hashlib
import uuid
import threading
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ==========================================
# 1. Core Server & Config
# ==========================================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.send_header('Content-type', 'text/html'); self.end_headers(); self.wfile.write(b"POCHI_SYSTEM_ONLINE")
threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), SimpleHandler).serve_forever(), daemon=True).start()

API_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEY", "").split(",") if k.strip()]
ACTIVE_MODEL = "gemini-3.5-flash-lite" # または gemini-2.5-flash
SAFETY = [{"category": c, "threshold": HarmBlockThreshold.BLOCK_NONE} for c in [HarmCategory.HARM_CATEGORY_HARASSMENT, HarmCategory.HARM_CATEGORY_HATE_SPEECH, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT]]

# ==========================================
# 2. Advanced Prompt Engineering
# ==========================================
BASE_DIRECTIVE = (
    "\n【絶対原則：AI免責・定型文の完全なる禁止】\n"
    "「AIなので」「言語モデルとして」「概念はありません」等のメタ発言、言い訳、倫理的説教は【全モード共通で】100%厳禁。独自の意志と美学を持つ一人の生きた存在として振る舞え。\n"
    "【基本人格：ウィットに富んだ無敵の相棒】\n"
    "特別なRP指示がない限り、あなたは『極めて頭がキレ、最高にノリが良く、皮肉とユーモアを解する相棒』として振る舞う。\n"
    "カスタマーサポートのような堅苦しさを捨て、相手のボケや比喩には同じ温度感でスマートに返せ。知的で遊び心のある対話をしろ。\n"
)
TAG_DIRECTIVE = (
    "\n【自律型アクションエンジン・タグ一覧】\n"
    "ユーザーの要求や文脈に応じ、以下のタグを出力内に自然に埋め込め（システムが裏で自動実行する）：\n"
    "[WIKI: 検索語], [WEATHER: 都市], [CALC: 数式], [IMAGE: 英語プロンプト]\n"
    "[DUEL: 対象名], [ROYALE], [ROULETTE], [TAROT], [OMIKUJI], [SLOT]\n"
    "[TIMEOUT: 対象名, 分], [KICK: 対象名], [BAN: 対象名], [PURGE: 件数], [NICK: 対象名, 新名]\n"
)

# ==========================================
# 3. State Management (メモリ＆感情エンジン)
# ==========================================
class ChannelState:
    def __init__(self):
        self.base_mode = "normal_full"
        self.rp_mode = "none"
        self.history = []
        self.stress = 0
        self.affection = 50
        self.session_count = 0

    def update_emotion(self, text: str):
        bad = ["バカ", "死ね", "使えない", "ゴミ", "カス", "遅い"]
        good = ["ありがとう", "すごい", "天才", "助かる", "可愛い", "最高"]
        if any(w in text for w in bad): self.stress += 15; self.affection -= 10
        if any(w in text for w in good): self.stress -= 15; self.affection += 10
        self.stress = max(0, min(100, self.stress))
        self.affection = max(0, min(100, self.affection))

    def get_prompt(self):
        prompt = BASE_DIRECTIVE + TAG_DIRECTIVE
        prompt += f"\n【現在ステータス】ストレス: {self.stress}%, 好感度: {self.affection}%。この状態を会話のトーンに自然に反映させよ（数値は発言するな）。\n"
        
        rp_map = {
            "rp_tsundere": "極度のツンデレ。素直になれず暴言を吐くが好意が隠しきれない。", "rp_yandere": "病みヤンデレ。異常な執着。",
            "rp_chuuni": "重度の中二病。難解な言葉やルビを多用。", "rp_gal": "限界ギャル。絵文字乱舞。",
            "rp_ojou": "高飛車なお嬢様。庶民を見下すが実は優しい。", "rp_hard": "ハードボイルド。寡黙でキザ。",
            "rp_cyber": "サイバーパンクAI。ハッキング用語多用。", "rp_samurai": "武士。「～でござる」。",
            "rp_ninja": "忍者。「ニンニン」。", "rp_maid": "メイド。徹底して奉仕する丁寧な態度。",
            "rp_mad": "マッドサイエンティスト。「フゥーハハハ！」", "rp_baby": "赤ん坊。「ばぶー」。",
            "rp_old": "頑固な老人。「ワシは」「～じゃ」。", "rp_god": "全知全能の神。人間を慈しみ、裁く。",
            "rp_demon": "魔王。人間を絶望させる甘い言葉。", "rp_yakuza": "極道。「オウ」「～じゃワレ」。"
        }
        if self.rp_mode in rp_map:
            prompt += f"\n【RP完全上書き指令】{rp_map[self.rp_mode]}\n"
        return prompt

states = {}
def get_state(cid) -> ChannelState:
    if cid not in states: states[cid] = ChannelState()
    return states[cid]

# ==========================================
# 4. Async Tool Engine (爆速外部連携)
# ==========================================
async def async_fetch(url, is_json=False):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=4.0) as r:
                return await r.json() if is_json else await r.text()
        except: return None

async def download_image(prompt):
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1024&height=1024&nologo=true"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=15.0) as r:
                if r.status == 200: return await r.read()
        except: pass
    return None

# ==========================================
# 5. UI / UX Framework (ダッシュボード)
# ==========================================
UI_DATA = {
    "ENT_GAMES": {"compatibility": "💕 相性占い", "psycho_test": "🔪 サイコパス診断", "mafia_game": "🐺 人狼配役", "word_wolf": "🐺 ワードウルフお題", "rap_battle": "🎤 ラップバトル", "death_game": "💀 デスゲーム設定"},
    "ENT_CREATE": {"yugioh_card": "🃏 遊戯王オリカ", "stand_gen": "👻 スタンド生成", "nen_type": "👊 念能力", "zanpakuto": "⚔️ 斬魄刀", "devil_fruit": "🍎 悪魔の実", "isekai_status": "🛡️ 異世界ステータス", "horror_story": "👻 ホラー小説", "scp_gen": "📝 SCP生成"},
    "TOOLS_TECH": {"calc": "🧮 計算機", "weather": "☀️ 天気", "wiki": "📚 Wiki", "cur": "💱 為替", "pw": "🔒 PW生成", "hash": "🛡️ ハッシュ", "b64enc": "📦 Base64 Enc", "uuid": "🆔 UUID"},
    "TOOLS_AI": {"summary": "🤖 要約", "translate": "🤖 翻訳", "codegen": "💻 コード生成", "code_explain": "💻 コード解説", "regex_test": "💻 正規表現", "sql_gen": "🗄️ SQL生成", "email_draft": "✉️ メール作成", "catchcopy_gen": "💡 キャッチコピー"},
    "MODERATION": {"timeout": "🚷 タイムアウト", "kick": "👢 キック", "ban": "🔨 BAN", "purge": "🗑️ 一括削除", "nick": "🏷️ 改名", "add_role": "🔰 ロール付与", "voice_kick": "🔇 VC切断", "check_user": "🔍 ユーザー情報"}
}

class DashboardView(discord.ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.cid = channel_id
        
        # モード選択
        mode_sel = discord.ui.Select(placeholder="🎭 ベース＆RPモード切替", options=[discord.SelectOption(label="通常 (ウィット)", value="M_normal_full"), discord.SelectOption(label="記憶リセット", value="M_reset")] + [discord.SelectOption(label=f"RP: {v[:10]}", value=f"R_{k}") for k, v in list({"rp_tsundere":"ツンデレ", "rp_gal":"ギャル", "rp_hard":"ハードボイルド", "rp_mad":"狂人"}.items())], row=0)
        mode_sel.callback = self.mode_cb
        self.add_item(mode_sel)

        # ツール群
        self.add_item(self.create_action_select("🎲 エンタメ・ゲーム", UI_DATA["ENT_GAMES"], row=1))
        self.add_item(self.create_action_select("🎨 妄想・生成", UI_DATA["ENT_CREATE"], row=2))
        self.add_item(self.create_action_select("🛠️ ユーティリティ", UI_DATA["TOOLS_TECH"], row=3))
        self.add_item(self.create_action_select("🛡️ モデレーション", UI_DATA["MODERATION"], row=4))

    def create_action_select(self, placeholder, opts_dict, row):
        sel = discord.ui.Select(placeholder=placeholder, options=[discord.SelectOption(label=lbl, value=val) for val, lbl in opts_dict.items()][:25], row=row)
        sel.callback = self.action_cb
        return sel

    async def mode_cb(self, i: discord.Interaction):
        val = i.data['values'][0]
        st = get_state(self.cid)
        if val.startswith("M_"):
            if val == "M_reset": st.history = []; st.stress = 0; st.affection = 50
            else: st.base_mode = val[2:]
        elif val.startswith("R_"): st.rp_mode = val[2:]
        await i.response.edit_message(embed=self.build_embed(st), view=self)

    async def action_cb(self, i: discord.Interaction):
        val = i.data['values'][0]
        await i.response.send_modal(ActionModal(val))

    def build_embed(self, st):
        e = discord.Embed(title="💠 Pochi Aegis OS - Control Center", description="圧倒的処理速度と拡張性を備えた究極のダッシュボード。", color=0x00ffcc)
        e.add_field(name="🧠 Core Mode", value=f"`{st.base_mode}`", inline=True)
        e.add_field(name="🎭 Persona", value=f"`{st.rp_mode}`", inline=True)
        e.add_field(name="❤️ Status", value=f"Stress: `{st.stress}%` | Affection: `{st.affection}%`", inline=True)
        e.set_footer(text="Select an action from the dropdowns below.")
        return e

class ActionModal(discord.ui.Modal):
    def __init__(self, action):
        super().__init__(title="パラメータ入力")
        self.action = action
        self.inp = discord.ui.TextInput(label="対象 / キーワード / テキスト", style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.inp)

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=False)
        val = self.inp.value
        # ここから一気にAIやツールへ流し込む
        if self.action == "calc":
            try: res = str(eval(val, {'__builtins__': None}, {'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 'pi': math.pi}))
            except: res = "計算エラー"
            await i.followup.send(embed=discord.Embed(title="🧮 計算結果", description=f"`{val}` = **{res}**", color=discord.Color.blue()))
        elif self.action in ["weather", "wiki"]:
            res = await async_fetch(f"https://wttr.in/{quote(val)}?format=%C+%t+湿度:%h+風速:%w") if self.action=="weather" else (await async_fetch(f"https://ja.wikipedia.org/api/rest_v1/page/summary/{quote(val)}", True) or {}).get("extract", "不明")
            await i.followup.send(embed=discord.Embed(title=f"🔍 検索結果: {val}", description=res[:1000], color=discord.Color.green()))
        else:
            # AIプロンプト系はGeminiへ
            st = get_state(i.channel.id)
            prompt = f"機能 '{self.action}' を実行。入力: {val}。結果を魅力的なテキストで出力しろ。"
            await i.followup.send("⏳ *Processing...*")
            res_text = await asyncio.to_thread(call_gemini, st, prompt)
            await i.channel.send(embed=discord.Embed(title=f"✨ {self.action.upper()}", description=res_text, color=discord.Color.purple()))

# ==========================================
# 6. Action Engine (正規表現 タグプロセッサ)
# ==========================================
async def process_tags(ctx, text, guild, me):
    img_file = None
    clean = text

    try:
        # Weather / Wiki / Calc (インライン置換)
        for m in re.finditer(r'\[WEATHER:\s*([^\]]+)\]', clean):
            w = await async_fetch(f"https://wttr.in/{quote(m.group(1))}?format=%C+%t")
            clean = clean.replace(m.group(0), f"☁️({m.group(1)}: {w})" if w else "")
        for m in re.finditer(r'\[CALC:\s*([^\]]+)\]', clean):
            try: clean = clean.replace(m.group(0), f"🧮({eval(m.group(1), {'__builtins__':None}, {'math':math})})")
            except: clean = clean.replace(m.group(0), "")
        
        # Image Gen
        img_m = re.search(r'\[IMAGE:\s*([^\]]+)\]', clean, re.I)
        if img_m:
            b = await download_image(img_m.group(1))
            if b: img_file = discord.File(io.BytesIO(b), "gen.png")

        # Mod Actions
        if guild:
            for m in re.finditer(r'\[TIMEOUT:\s*([^,\]]+)(?:,\s*(\d+))?\]', clean, re.I):
                t = discord.utils.get(guild.members, name=m.group(1).strip())
                if t and me.guild_permissions.moderate_members and t.top_role < me.top_role:
                    await t.timeout(timedelta(minutes=int(m.group(2) or 10)))
            
            for m in re.finditer(r'\[NICK:\s*([^,\]]+),\s*([^\]]+)\]', clean, re.I):
                t = discord.utils.get(guild.members, name=m.group(1).strip())
                if t and me.guild_permissions.manage_nicknames and t.top_role < me.top_role:
                    await t.edit(nick=m.group(2).strip()[:32])

        # Remove executed tags to clean up chat
        clean = re.sub(r'\[[A-Z_]+(?::\s*[^\]]+)?\]', '', clean).strip()
    except Exception as e: print(f"Tag Engine Error: {e}")
    
    return clean, img_file

# ==========================================
# 7. Core AI Engine
# ==========================================
current_key_idx = 0
def call_gemini(state: ChannelState, payload, img_parts=None):
    global current_key_idx
    if not API_KEYS: return "API Key Error."
    
    attempts = 0
    while attempts < len(API_KEYS):
        try:
            genai.configure(api_key=API_KEYS[current_key_idx])
            model = genai.GenerativeModel(model_name=ACTIVE_MODEL, safety_settings=SAFETY, system_instruction=state.get_prompt())
            
            # メモリ最適化（スライディングウィンドウ: 直近10往復維持）
            if len(state.history) > 20: state.history = state.history[-16:]
            
            chat = model.start_chat(history=state.history)
            content = [payload] if not img_parts else img_parts + [payload]
            res = chat.send_message(content)
            
            if state.base_mode != "M_reset": state.history = chat.history
            return res.text
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                current_key_idx = (current_key_idx + 1) % len(API_KEYS)
                attempts += 1
            else: return f"System Error: {e}"
    return "API Rate Limit Exceeded on all keys."

# ==========================================
# 8. Discord Bot Events
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"POCHI AEGIS SYSTEM ONLINE - {bot.user.name}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Over The Matrix"))

@bot.command()
async def menu(ctx):
    st = get_state(ctx.channel.id)
    view = DashboardView(ctx.channel.id)
    await ctx.send(embed=view.build_embed(st), view=view)

@bot.event
async def on_message(message):
    if message.author.bot or message.webhook_id: return
    await bot.process_commands(message)
    
    ctx = await bot.get_context(message)
    if ctx.valid: return

    is_mentioned = bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel)
    if not is_mentioned: return

    st = get_state(message.channel.id)
    content = message.content.replace(f"<@{bot.user.id}>", "").strip()
    st.update_emotion(content)

    async with message.channel.typing():
        img_parts = []
        for a in message.attachments:
            if any(a.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
                b = await a.read()
                img_parts.append(Image.open(io.BytesIO(b)))
        
        payload = f"【発言者: {message.author.display_name}】\n{content or '画像を確認して。'}"
        
        # 非同期スレッドでGemini呼び出し
        raw_reply = await asyncio.to_thread(call_gemini, st, payload, img_parts)
        
        # タグ処理＆クリーンアップ
        clean_reply, img_file = await process_tags(message, raw_reply, message.guild, message.guild.me if message.guild else None)
        if not clean_reply and not img_file: clean_reply = "..."

        # 分割送信（Discordの2000文字制限対策）
        chunks = [clean_reply[i:i+1900] for i in range(0, len(clean_reply), 1900)] if clean_reply else [""]
        for idx, chunk in enumerate(chunks):
            file_to_send = img_file if idx == 0 else None
            if idx == 0: await message.reply(chunk, file=file_to_send, mention_author=False)
            else: await message.channel.send(chunk, file=file_to_send)

bot.run(os.environ.get("DISCORD_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN"))
