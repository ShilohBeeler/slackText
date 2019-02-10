from flask import Flask, request, Response
import os
import time
import re
import threading
import json
from slackclient import SlackClient
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

TWILIO_NUMBER = os.environ.get('TWILIO_NUMBER', None)
USER_NUMBER = os.environ.get('MY_NUMBER', None)

twilio_client = Client()
slack_client = SlackClient(os.environ.get('SLACK_BOT_TOKEN'))
starterbot_id = None
RTM_READ_DELAY = 1
EXAMPLE_COMMAND = "do"
MENTION_REGEX = "^<@(|[WU].+?)>(.*)"

app = Flask(__name__)


@app.route('/')
def hello_world():
    return 'Hello World!'


@app.route('/twilio', methods=['POST'])
def twilio_post():
    response = MessagingResponse()
    message = request.form['Body']
    sender = request.form['From']
    with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
        monitor_json = json.load(f)
        if not sender in monitor_json[1]:
            monitor_json[1][sender] = {"alias": "None", "last_channel": "#general", "channels": []}
        f.seek(0)
        f.write(json.dumps(monitor_json))
        f.truncate()
        f.close()
    if message.startswith("command"):
        twilio_commands(message, sender)
    elif sender in monitor_json[1]:
        last_channel = monitor_json[1][sender]["last_channel"]
        username = sender if monitor_json[1][sender]["alias"] == "None" else \
            monitor_json[1][sender]["alias"]
        slack_client.api_call("chat.postMessage", channel=last_channel, text=message, username=username)
    else:
        slack_client.api_call("chat.postMessage", channel="#general", text=message, username=request.form['From'])
    return Response(response.toxml(), mimetype="text/xml"), 200


def slack_main():
    while True:
        command, channel = parse_bot_commands(slack_client.rtm_read())
        if command:
            handle_command(command, channel)
        time.sleep(RTM_READ_DELAY)


def twilio_commands(message, sender):
    split = message.split()
    channel_data = slack_client.api_call("channels.list")["channels"]
    if split[1] == "list":
        channel_list = ""
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r") as f:
            monitor_json = json.load(f)
            for chan in channel_data:
                channel_list += chan["name"]
                if chan["id"] in monitor_json[1][sender]["channels"]:
                    channel_list += " (Monitored)"
                channel_list += "\n"
            twilio_client.messages.create(to=sender, from_=TWILIO_NUMBER, body="Channels:\n" + channel_list)
            f.close()
    elif split[1] == "monitor":
        channel = split[2]
        for chan in channel_data:
            if chan["name"] == channel:
                channel = chan["id"]
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            if not channel in monitor_json[0]:
                monitor_json[0][channel] = []
            phone_number = sender
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"alias": "None", "last_channel": "#general", "channels": []}
            if not phone_number in monitor_json[0][channel]:
                monitor_json[0][channel].append(phone_number)
                monitor_json[1][phone_number]["channels"].append(channel)
                response = "Your number " + phone_number + " has been added to this channel's monitoring list!"
            else:
                response = "Your number was already on the list."
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.close()
        twilio_client.messages.create(to=sender, from_=TWILIO_NUMBER, body=response)
    elif split[1] == "demonitor":
        channel = split[2]
        for chan in channel_data:
            if chan["name"] == channel:
                channel = chan["id"]
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            if not channel in monitor_json[0]:
                monitor_json[0][channel] = []
            phone_number = sender
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"alias": "None", "last_channel": "#general", "channels": []}
            if phone_number in monitor_json[0][channel]:
                monitor_json[0][channel].remove(phone_number)
                monitor_json[1][phone_number]["channels"].remove(channel)
                response = "Your number " + phone_number + " has been removed from this channel's monitoring list!"
            else:
                response = "Your number wasn't on the list."
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.truncate()
            f.close()
        twilio_client.messages.create(to=sender, from_=TWILIO_NUMBER, body=response)
    elif split[1] == "alias":
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            phone_number = sender
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"alias": "None", "last_channel": "#general", "channels": []}
            monitor_json[1][phone_number]["alias"] = split[2]
            response = "The alias for " + phone_number + " has been set to: " + split[2]
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.truncate()
            f.close()
        twilio_client.messages.create(to=sender, from_=TWILIO_NUMBER, body=response)
    elif split[1] == "direct":
        channel = split[2]
        send_message = " ".join(split[2:])
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r") as f:
            monitor_json = json.load(f)
            if sender in monitor_json[1]:
                username = sender if monitor_json[1][sender]["alias"] == "None" else \
                    monitor_json[1][sender]["alias"]
            else:
                username = sender
        slack_client.api_call("chat.postMessage", channel=channel, text=send_message, username=username)
        twilio_client.messages.create(to=sender, from_=TWILIO_NUMBER, body="Message sent to #" + channel + "!")


def parse_bot_commands(slack_events):
    for event in slack_events:
        if event["type"] == "message" and not "subtype" in event:
            user_id, message = parse_direct_mention(event["text"])
            if user_id == starterbot_id:
                return message, event["channel"]
            else:
                monitor_event(event["text"], event["channel"], event["user"])
    return None, None


def parse_direct_mention(message_text):
    matches = re.search(MENTION_REGEX, message_text)
    return (matches.group(1), matches.group(2).strip()) if matches else (None, message_text)


def handle_command(command, channel):
    default_response = "Not sure what you mean."

    response = None

    if (command.startswith(EXAMPLE_COMMAND)):
        response = "Nice."
    elif (command.startswith("passthrough")):
        twilio_client.messages.create(to=USER_NUMBER, from_=TWILIO_NUMBER, body=command[12:])
        return
    elif (command.startswith("monitor")):
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            if not channel in monitor_json[0]:
                monitor_json[0][channel] = []
            phone_number = command[8:]
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"alias": "None", "last_channel": "#general", "channels": []}
            if not phone_number in monitor_json[0][channel]:
                monitor_json[0][channel].append(phone_number)
                monitor_json[1][phone_number]["channels"].append(channel)
                response = "Your number " + phone_number + " has been added to this channel's monitoring list!"
            else:
                response = "Your number was already on the list."
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.close()
    elif (command.startswith("demonitor")):
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            if not channel in monitor_json[0]:
                monitor_json[0][channel] = []
            phone_number = command[10:]
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"alias": "None", "last_channel": "#general", "channels": []}
            if phone_number in monitor_json[0][channel]:
                monitor_json[0][channel].remove(phone_number)
                monitor_json[1][phone_number]["channels"].remove(channel)
                response = "Your number " + phone_number + " has been removed from this channel's monitoring list!"
            else:
                response = "Your number wasn't on the list."
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.truncate()
            f.close()
    elif (command.startswith("alias")):
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            phone_number = command.split()[1]
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"alias": "None", "last_channel": "#general", "channels": []}
            monitor_json[1][phone_number]["alias"] = command.split()[2]
            response = "The alias for " + phone_number + " has been set to: " + command.split()[2]
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.truncate()
            f.close()

    slack_client.api_call("chat.postMessage", channel=channel, text=response or default_response)


def monitor_event(message, channel, user):
    with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
        monitor_json = json.load(f)
        if channel in monitor_json[0] and len(monitor_json[0][channel]) != 0:
            username = slack_client.api_call("users.info", user=user)["user"]["profile"]["display_name"]
            channel_name = slack_client.api_call("channels.info", channel=channel)["channel"]["name"]
            response = username + " in channel " + channel_name + " said: " + message
            for phone_number in monitor_json[0][channel]:
                twilio_client.messages.create(to=phone_number, from_=TWILIO_NUMBER, body=response)
                monitor_json[1][phone_number]["last_channel"] = channel
        f.seek(0)
        f.write(json.dumps(monitor_json))
        f.close()


if __name__ == '__main__':
    if not os.path.exists(os.path.expanduser("~") + "/slackText"):
        os.mkdir(os.path.expanduser("~") + "/slackText")
    if not os.path.isfile(os.path.expanduser("~") + "/slackText/numbers_channels.json"):
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "w") as f:
            channels = {}
            numbers = {}
            initjson = [channels, numbers]
            f.write(json.dumps(initjson))
            f.close()
    if slack_client.rtm_connect(with_team_state=False):
        print("Bot running!")
        starterbot_id = slack_client.api_call("auth.test")["user_id"]
        t = threading.Thread(target=slack_main, name="SlackBot")
        t.start()
    else:
        print("Connection failed.")
    app.run()
