import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from urllib.parse import parse_qs, urlencode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# API configurations
API_CONFIGS = [
    {"BaseUrl": "https://partners-us-east1.zeronetworks.com/api/v1/internal", "KeyName": "us-east1-key", "Region": "us-east1"},
    {"BaseUrl": "https://partners-eu-west12.zeronetworks.com/api/v1/internal", "KeyName": "eu-west12-key", "Region": "eu-west12"}
]

DEPLOYMENTS_URI = "/deployments"
SLACK_CHANNEL = "C123ABC456"  # Replace with your Slack channel ID


def invoke_api_call(base_url, endpoint, headers):
    """Calls the specified API endpoint."""
    full_url = f"{base_url}{endpoint}"
    try:
        response = requests.get(full_url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"API Call Failed: {e}")
        return None


def format_slack_message(environments):
    """Formats the Slack message with environment details and deployment buttons."""
    blocks = [{
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Select Environment to pull logs",
            "emoji": True
        }
    }]

    for env in environments:
        emoji = ":football:" if env.get('region') == "us-east1" else ":soccer:"
        env_name = env.get('Name') or env.get('name') or "Unknown Name"
        env_id = env.get('id') or "Unknown ID"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} `{env_name} : {env_id}` "
            }
        })
        #blocks.append({
        #    "type": "section",
        #    "text": {
        #        "type": "mrkdwn",
        #        "text": f"``"
        #    }
        #})

        # Get deployments for each environment
        deployment_headers = env.get('_headers', {}).copy()
        deployment_headers['zn-env-id'] = env_id
        base_url = env.get('_baseUrl')
        deployment_response = invoke_api_call(base_url, DEPLOYMENTS_URI, deployment_headers)

        if deployment_response and "detailedDeploymentsFormatted" in deployment_response:
            for dep in deployment_response["detailedDeploymentsFormatted"]:
                value = json.dumps({
                    "id": env_id,
                    "region": env.get('region'),
                    "deployment": dep.get('id')
                })
                style = "primary" if dep.get('state') == "Primary" else "danger"
                dep_name = dep.get('name') or "Unnamed Deployment"

                blocks.append({
                    "type": "actions",
                    "elements": [{
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": f"Get Logs for {dep_name}"
                        },
                        "value": value,
                        "action_id": "get_logs",
                        "style": style
                    }]
                })
        elif deployment_response is None:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Error fetching deployments.*"
                }
            })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*No deployments found.*"
                }
            })

    return {
        "channel": SLACK_CHANNEL,
        "text": "Get Support Details",
        "blocks": blocks
    }


@app.route('/', methods=['POST'])
def slack_trigger():
    """Handles the Slack app trigger."""
    try:
        body = parse_qs(request.get_data(as_text=True))
        text = body.get('text', [None])[0]

        if not text:
            return jsonify({
                "response_type": "ephemeral",
                "text": "Please provide an environment name to search for."
            }), 200

        # Construct environment search URI
        encoded_text = urlencode({
            '_filters': json.dumps([{'id': 'name', 'includeValues': [text], 'excludeValues': []}]),
            '_limit': 5
        })
        env_uri = f"/provisioning/environments/?{encoded_text}"

        aggregated_results = []
        for config in API_CONFIGS:
            secret_value = os.environ.get(config['KeyName'])
            if not secret_value:
                logging.warning(f"Environment variable '{config['KeyName']}' not set.")
                continue

            headers = {
                "Authorization": secret_value,
                "content-type": "application/json"
            }
            response_obj = invoke_api_call(config['BaseUrl'], env_uri, headers)
            if response_obj and "items" in response_obj:
                for item in response_obj['items']:
                    item['region'] = config['Region']
                    item['_baseUrl'] = config['BaseUrl']
                    item['_headers'] = headers
                    aggregated_results.append(item)

        logging.info("Aggregated results: %s", json.dumps(aggregated_results, indent=2))

        if aggregated_results:
            slack_message = format_slack_message(aggregated_results)
            SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
            if not SLACK_WEBHOOK_URL:
                logging.error("SLACK_WEBHOOK_URL is not set.")
                return jsonify({
                    "response_type": "ephemeral",
                    "text": "Slack webhook not configured."
                }), 500

            slack_response = requests.post(SLACK_WEBHOOK_URL, headers={'Content-Type': 'application/json'}, json=slack_message)
            slack_response.raise_for_status()
            return jsonify({
                "response_type": "ephemeral",
                "text": f"Found {len(aggregated_results)} matching environments. Details sent to the channel."
            }), 200
        else:
            return jsonify({
                "response_type": "ephemeral",
                "text": f"No results found for '{text}' in either API."
            }), 200

    except Exception as e:
        logging.exception("Error processing Slack request")
        return jsonify({
            "response_type": "ephemeral",
            "text": "An error occurred while processing your request."
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
