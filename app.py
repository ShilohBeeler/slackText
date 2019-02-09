from flask import Flask, request, Response
import os
import time
import re
import threading
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
    if request.form['From'] == USER_NUMBER:
        message = request.form['Body']
        slack_client.api_call("chat.postMessage", channel="#general", text=message, username='textBot')
        return Response(response.toxml(), mimetype="text/xml"), 200

def slack_main():
    while True:
        print()
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
    return None, None

def parse_direct_mention(message_text):
    matches = re.search(MENTION_REGEX, message_text)
    return (matches.group(1), matches.group(2).strip()) if matches else (None, None)

def handle_command(command, channel):
    default_response = "Not sure what you mean."

    response = None

    if(command.startswith(EXAMPLE_COMMAND)):
        response = "Nice."
    if(command.startswith("passthrough")):
        twilio_client.messages.create(to=USER_NUMBER, from_=TWILIO_NUMBER, body=command[12:])
        return

    slack_client.api_call("chat.postMessage", channel=channel, text=response or default_response)


if __name__ == '__main__':
    if slack_client.rtm_connect(with_team_state=False):
        print("Bot running!")
        starterbot_id = slack_client.api_call("auth.test")["user_id"]
        t = threading.Thread(target=slack_main, name="SlackBot")
        t.start()
    else:
        print("Connection failed.")
    app.run()


