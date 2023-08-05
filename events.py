import bot
import importlib

handlers = {}

def load(load_events):
    global handlers

    for event in load_events:
        handlers[event] = importlib.import_module(f"event_handlers.{event}")

def register(load_events):
    for event in load_events:
        bot.client.__dict__.update({event: handlers[event].handle})

