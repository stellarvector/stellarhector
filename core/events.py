import logging
import core.bot as bot
import importlib

handlers = {}

def load(load_events):
    global handlers

    for event in load_events:
        handlers[event] = importlib.import_module(f"event_handlers.{event}")

    logging.getLogger("bot").debug(f"{len(load_events)} commands loaded")

def register(load_events):
    for event in load_events:
        bot.client.__dict__.update({event: handlers[event].handle})

    logging.getLogger("bot").debug(f"{len(load_events)} events registered")
