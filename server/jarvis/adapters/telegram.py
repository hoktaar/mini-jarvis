"""Telegram-Bot (Long-Polling, kein offener Port). Nur freigegebene Benutzer-IDs.

Hinweis: Nachrichten laufen über Telegrams Server.
"""

from __future__ import annotations

from loguru import logger

from jarvis.adapters import alarm_text
from jarvis.textpipe import chat


class TelegramAdapter:
    def __init__(self, services):
        self.services = services
        self.cfg = services.cfg.adapters.telegram
        self.token = services.secrets.get("telegram_bot_token", "")
        self.app = None
        self._sinks: dict[int, object] = {}

    def allowed(self, user_id: int) -> bool:
        return user_id in self.cfg.allowed_user_ids

    def session(self, user, chat_id: int):
        device = self.services.devices.for_adapter_user("telegram", str(user.id), user.first_name or str(user.id))
        session = self.services.session_for(device)
        if device.id not in self._sinks:
            async def sink(event, _chat=chat_id):
                text = alarm_text(event)
                if text and self.app is not None:
                    await self.app.bot.send_message(_chat, text)
            self._sinks[device.id] = sink
            session.sinks.append(sink)
        return session

    async def start(self) -> None:
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

        if not self.token:
            raise RuntimeError("telegram_bot_token fehlt")
        self.app = Application.builder().token(self.token).build()
        self.app.add_handler(CommandHandler("start", self.on_start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        self.app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.on_voice))
        self.app.add_handler(CallbackQueryHandler(self.on_button))
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram-Adapter läuft")

    async def stop(self) -> None:
        if self.app is not None:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def _reply(self, message, result: dict) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        text = result.get("reply") or "Erledigt."
        markup = None
        if result.get("needs_confirmation"):
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Ja", callback_data="ja"),
                                            InlineKeyboardButton("❌ Nein", callback_data="nein")]])
        if result.get("cloud"):
            text += " ☁️"
        await message.reply_text(text, reply_markup=markup)

    async def on_start(self, update, context) -> None:
        user = update.effective_user
        if not self.allowed(user.id):
            await update.message.reply_text(f"Nicht freigegeben. Deine Telegram-ID: {user.id}")
            return
        await update.message.reply_text("Hallo! Ich bin Jarvis. Schreib mir oder schick eine Sprachnachricht.")

    async def on_text(self, update, context) -> None:
        user = update.effective_user
        if not self.allowed(user.id):
            await update.message.reply_text(f"Nicht freigegeben. Deine Telegram-ID: {user.id}")
            return
        session = self.session(user, update.effective_chat.id)
        await context.bot.send_chat_action(update.effective_chat.id, "typing")
        await self._reply(update.message, await chat(session, update.message.text, speak=False))

    async def on_voice(self, update, context) -> None:
        from jarvis.providers import transcribe_audio

        user = update.effective_user
        if not self.allowed(user.id):
            return
        media = update.message.voice or update.message.audio
        file = await media.get_file()
        data = bytes(await file.download_as_bytearray())
        try:
            text = await transcribe_audio(self.services.cfg, self.services.secrets, data, "voice.ogg")
        except Exception as e:  # noqa: BLE001
            await update.message.reply_text(f"Sprachnachricht nicht verstanden: {e}")
            return
        if not text:
            await update.message.reply_text("Ich habe nichts verstanden.")
            return
        await update.message.reply_text(f"🎙️ „{text}“")
        session = self.session(user, update.effective_chat.id)
        await self._reply(update.message, await chat(session, text, speak=False))

    async def on_button(self, update, context) -> None:
        query = update.callback_query
        await query.answer()
        if not self.allowed(query.from_user.id):
            return
        session = self.session(query.from_user, query.message.chat.id)
        await query.edit_message_reply_markup(None)
        await self._reply(query.message, await chat(session, query.data, speak=False))
