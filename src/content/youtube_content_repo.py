import sys
import os
sys.path.append("../src")

import pickle
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from googleapiclient.http import MediaFileUpload
import ai.gpt as gpt3
from storage.firebase_storage import firebase_storage_instance, PostingPlatform
import storage.dropbox_storage as dropbox_storage
import pickle
import json
import ai.gpt as gpt
import media.video_editor as video_editor
from ai.gpt_write_story import create_story_and_scenes
import utility.scheduler as scheduler
import media.video_converter as video_converter

# Build the YouTube API client
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

CLIENT_SECRET_FILE = "google_youtube_client.json"
SCOPES = [
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/youtubepartner'
]

# Note that this works only for shorts ATM
def complete_scheduling_and_posting_of_video ( db_remote_path ): 

    creds = get_youtube_credentials()
    if creds == '': return ''

    youtube = googleapiclient.discovery.build(
        API_SERVICE_NAME, 
        API_VERSION, 
        credentials = creds
    )

    summary_file = os.path.join('src', 'outputs', 'summary_output.txt')

    title = gpt3.prompt_to_string_from_file(
        os.path.join('src', 'input_prompts', 'youtube_title.txt'),
        feedin_source_file=summary_file
    )
    title = title.replace('"', '')

    description = gpt3.prompt_to_string_from_file(
        prompt_source_file=os.path.join('src', 'input_prompts', 'youtube_description.txt'),
        feedin_source_file=summary_file
    )

    upload_file_path = dropbox_storage.download_file_to_local_path(db_remote_path)

    posting_time = scheduler.get_best_posting_time(PostingPlatform.YOUTUBE)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": "17"
            },
            "status": {
                "privacyStatus": "private",
                "embeddable": True,
                "license": "youtube",
                "publicStatsViewable": True,
                "publishAt": posting_time
            }
        },
        media_body=MediaFileUpload(upload_file_path)
    )
    try:
        response = request.execute()
        print(f'YT posting scheduled!\n{response}')    
    except Exception as e:    
        print(e)
        response = e
    return response

def scheduled_youtube_video ( remote_video_url ):  
    summary_file = os.path.join('src', 'outputs', 'summary_output.txt')
    title = gpt3.prompt_to_string_from_file(
        os.path.join('src', 'input_prompts', 'youtube_title.txt'),
        feedin_source_file=summary_file
    )
    title = title.replace('"', '')
    description = gpt3.prompt_to_string_from_file(
        prompt_source_file=os.path.join('src', 'input_prompts', 'youtube_description.txt'),
        feedin_source_file=summary_file
    )
    yt_tags = gpt3.prompt_to_string_from_file(
        prompt_source_file=os.path.join('src', 'input_prompts', 'youtube_tags.txt'),
        feedin_source_file=summary_file
    )
    tags_array = yt_tags.replace(',', '').replace('#', '').split(' ')

    payload = dict()
    payload['title'] = title
    payload['description'] = description
    payload['remote_video_url'] = remote_video_url
    payload['tags']: tags_array

    result = firebase_storage_instance.upload_scheduled_post(
        PostingPlatform.YOUTUBE,
        payload
    )
    return result

def get_youtube_credentials():
    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    # Get credentials and create an API client
    # Get the path to the parent directory
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    file_path = os.path.join(parent_dir, CLIENT_SECRET_FILE)
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(file_path, SCOPES)

    # get cached values
    token_file = os.path.join('src', 'yt_access_token.pickle')
    with open(token_file, "rb") as input_file:
        credentials = pickle.load(input_file)

    if (credentials == ''):
        credentials = flow.run_local_server()
        
        with open(token_file, 'wb') as token:
            pickle.dump(credentials, token)
                    
    print(f'Youtube authentication complete with creds: {credentials}')
    return credentials

def post_scheduled_upload_video_to_youtube():
    '''
    # Sample Python code for youtube.videos.insert
    # NOTES:
    # 1. This sample code uploads a file and can't be executed via this interface.
    #    To test this code, you must run it locally using your own API credentials.
    #    See: https://developers.google.com/explorer-help/code-samples#python
    # 2. This example makes a simple upload request. We recommend that you consider
    #    using resumable uploads instead, particularly if you are transferring large
    #    files or there's a high likelihood of a network interruption or other
    #    transmission failure. To learn more about resumable uploads, see:
    #    https://developers.google.com/api-client-library/python/guide/media_upload

    '''
    earliest_scheduled_datetime_str = firebase_storage_instance.get_earliest_scheduled_datetime(PostingPlatform.YOUTUBE)
    if (earliest_scheduled_datetime_str == ''): return 'no posts scheduled'
    print(f'YT last posted time: {earliest_scheduled_datetime_str}')
    
    # ready_to_post = time_utils.is_current_posting_time_within_window(earliest_scheduled_datetime_str)
    # if (ready_to_post):  
    if (True): 
        post_params_json = firebase_storage_instance.get_specific_post(
            PostingPlatform.YOUTUBE, 
            earliest_scheduled_datetime_str
        )
        try:
            post_params = json.loads(post_params_json)
            if (post_params['remote_video_url'] == 'no movie url'):
                #recursive deletion if we do not have a movie url
                firebase_storage_instance.delete_post(
                    PostingPlatform.YOUTUBE,
                    earliest_scheduled_datetime_str
                )
                post_scheduled_upload_video_to_youtube()

            print('\nYOUTUBE post_params: ', post_params, '\n')
        except:
            print('YT error parsing post params')
            print('post_params_json: ', post_params_json)
            return 'Error parsing post params'

        upload_file_path = video_converter.get_downloaded_video_local_path(
            post_params['remote_video_url']
        )
        youtube = googleapiclient.discovery.build(
            API_SERVICE_NAME, 
            API_VERSION, 
            credentials = get_youtube_credentials()
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": post_params['title'],
                    "description": post_params['description'],
                    "categoryId": "17"
                },
                "status": {
                    "privacyStatus": "private",
                    "embeddable": True,
                    "license": "youtube",
                    "publicStatsViewable": True,
                    "publishAt": earliest_scheduled_datetime_str
                }
            },
            media_body=MediaFileUpload(upload_file_path)
        )
        try:
            response = request.execute()
            print(f'YT success {response}')

            firebase_storage_instance.delete_post(
                PostingPlatform.YOUTUBE, 
                earliest_scheduled_datetime_str
            )
        except Exception as e:    
            response = e
        return response

def post_youtube_video():    
    response = post_scheduled_upload_video_to_youtube()
    print(f'Youtube response {response}') 

def process_initial_video_download_transcript(db_remote_path, should_summarize=True):
    filename = video_converter.local_video_to_mp3(db_remote_path)
    transcriptname = gpt.mp3_to_transcript(filename)
    if (should_summarize): gpt.transcript_to_summary(transcriptname, filename) 

def schedule_video_story(image_query):
    gpt.generate_video_with_prompt(
        prompt_source=os.path.join("src", "input_prompts", "story.txt"), 
        video_meta_data=image_query,
        should_polish_post=True,
        post_num=1,
        upload_func=create_story_and_scenes
    )
    video_remote_url = video_editor.edit_movie_for_remote_url(image_query)
    if (video_remote_url != ''):
        result = complete_scheduling_and_posting_of_video(video_remote_url)
        print(f'youtube schedule result\n\n{result}')
    else:
        print('something went wrong with our video remote url')    

def get_recent_videos():
    # Set up the YouTube API client
    youtube = googleapiclient.discovery.build("youtube", "v3", credentials=get_youtube_credentials())

    # Retrieve the most recent videos uploaded to your channel
    request = youtube.search().list(
        part="snippet",
        channelId='UCI4DX-IyQ8KAGhPWE0Qr7Vg',
        order="date",
        type="video",
        maxResults=10
    )
    response = request.execute()

    # Print the title and video ID of each video in the response
    for item in response["items"]:
        print(f'Title: {item["snippet"]["title"]}')
        print(f'Video ID: {item["id"]["videoId"]}')