import discord
import asyncio

def get_new_channel_position(category, new_channel_name):
    channels = category.channels
    channel_map = sorted(map(lambda c: (c.name.replace("solved_", "zzzzzz_"), c.position), channels[1:]), key=channel_sort_key)
    print(channel_map)
    print(new_channel_name)

    return calculate_position(new_channel_name.replace("solved_", "zzzzzz_"), channel_map)

def calculate_position(name, channel_map):
    last_position = 1
    new_position = None

    for map_item in channel_map:
        channel_name, position = map_item

        if channel_name < name:
            last_position = position
            continue

        new_position = 1 + (position+last_position)//2
        break

    if new_position is None:
        new_position = last_position + 100

    print(last_position, new_position)
    return new_position

def channel_sort_key(channel_map_entry):
    return channel_map_entry[0]
