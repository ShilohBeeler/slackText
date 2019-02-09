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
    with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r") as f:
        monitor_json = json.load(f)
        if request.form['From'] in monitor_json[1]:
            last_channel = monitor_json[1][request.form['From']]["last_channel"]
            message = request.form['Body']
            slack_client.api_call("chat.postMessage", channel=last_channel, text=message, username=request.form['From'])
        else:
            message = request.form['Body']
            slack_client.api_call("chat.postMessage", channel="#general", text=message, username=request.form['From'])
        f.close()
        return Response(response.toxml(), mimetype="text/xml"), 200

def slack_main():
    while True:
        command, channel = parse_bot_commands(slack_client.rtm_read())
        if command:
            handle_command(command, channel)
        time.sleep(RTM_READ_DELAY)

def parse_bot_commands(slack_events):
    for event in slack_events:
        if event["type"] == "message" and not "subtype" in event:
            user_id, message = parse_direct_mention(event["text"])
            if user_id == starterbot_id:
                return message, event["channel"]
            else:
                monitor_event(message, event["channel"], event["user"])
    return None, None

def parse_direct_mention(message_text):
    matches = re.search(MENTION_REGEX, message_text)
    return (matches.group(1), matches.group(2).strip()) if matches else (None, message_text)

def handle_command(command, channel):
    default_response = "Not sure what you mean."

    response = None

    if(command.startswith(EXAMPLE_COMMAND)):
        response = "Nice."
    if(command.startswith("passthrough")):
        twilio_client.messages.create(to=USER_NUMBER, from_=TWILIO_NUMBER, body=command[12:])
        return
    if(command.startswith("monitor")):
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            if not channel in monitor_json[0]:
                monitor_json[0][channel] = []
            phone_number = command[8:]
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"last_channel": "#general", "channels": []}
            if not phone_number in monitor_json[0][channel]:
                monitor_json[0][channel].append(phone_number)
                monitor_json[1][phone_number]["channels"].append(channel)
                response = "Your number " + phone_number + " has been added to this channel's monitoring list!"
            else:
                response = "Your number was already on the list."
            f.seek(0)
            f.write(json.dumps(monitor_json))
            f.close()
    if (command.startswith("demonitor")):
        with open(os.path.expanduser("~") + "/slackText/numbers_channels.json", "r+") as f:
            monitor_json = json.load(f)
            if not channel in monitor_json[0]:
                monitor_json[0][channel] = []
            phone_number = command[10:]
            if not phone_number in monitor_json[1]:
                monitor_json[1][phone_number] = {"last_channel": "#general", "channels": []}
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