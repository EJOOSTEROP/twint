'''
Main for Flask app in Google Cloud's AppEngine

TODO: Maybe can specify a file name instead of relying on 'main.py'?
'''

import twint
import pandas
import flask

from google.cloud import storage

from shutil import copyfile
from datetime import datetime, timedelta, timezone
import json
import yaml
import os

from os import listdir
 

# If `entrypoint` is not defined in app.yaml, App Engine will look for an app
# called `app` in `main.py`.
app = flask.Flask(__name__)

# Available at http://127.0.0.1:8080/ when using Development Docker image and VS Code
@app.route("/", methods=["GET"])
def TweetSearch():
    '''
    Basic example using Google Cloud, Flask, Twint
    '''

    c = twint.Config()
    c.Search = "airtransat"
    c.Limit = 2
    c.Hide_output = True
    c.Pandas = True
    twint.run.Search(c)
    
    df = twint.storage.panda.Tweets_df
    tweets = str(df.sample(5)['tweet'])
    
    return tweets


'''
TODO: randomize list of files
TODO: Optimize memory usage: 1 file for TWINT uses ~300MB or so; 6 use too much for F2 (now trying F4)
TODO: return a meaningful '200' message? Now it says it fails; and it indeed shows an error/timeout; but it does update results file
TODO: Set custom entrypoint (gunicorn, nginx)- some incomplete info: https://stackoverflow.com/questions/67463034/google-app-engine-using-custom-entry-point-with-python
'''

@app.route("/configgcp", methods=["GET"])
def gcp_TestConfig():
    '''
    Returns a representation of what is contained in the configgcp.yaml
    configuration file.
    '''
    result = ParseFilesFromConfig(ReadConfigFileGCP())
    return str(result)


@app.route("/updategcp", methods=["GET"])
def gcp_AppendToFilesJSON():
    '''
    Adds tweets to files specified in configgcp.yalm (on Google Storage)

    The files are captured on Google Storage. If no file exists it will be created.
    The function may take a long time to run. There is no meaningful return value.
    This works in Google Cloud App Engine environment.
    '''
    files = ParseFilesFromConfig(ReadConfigFileGCP())

    #TODO: use GCP credentials; would allow for local testing
    storage_client = storage.Client()
    bucketName = 'industrious-eye-330414.appspot.com'
    bucket = storage_client.get_bucket(bucketName)


    for f in files:
        #TODO: prevent copying if file already exists in /tmp
        #TODO: logging: adding tweets to file xyz
        _gcp_CopyFileFromBucket(f['bucketfilepath'], f['localfilepath'], bucket)
        SearchNewerTweets(f['localfilepath'], f['search'])
        if f.get('historyfill', False):
            SearchEarlierTweets(f['localfilepath'], f['search'])
        _gcp_CopyFileToBucket(f['localfilepath'], f['bucketfilepath'], bucket)
        #TODO: logging: completed adding tweets to file xyz
    
    return '200' # has to be a string


@app.route("/update", methods=["GET"])
def AppendToFilesJSON():
    '''
    Similar to gcp_AppendToFilesJSON above, but uses local files only.

    Not maintained.
    TODO: just remove?
    '''
    bucket_dir = os.path.join('tmpdata', 'src')
    local_dir = os.path.join('tmpdata', 'dst')

    fileinfo = {'bucketfilepath' : os.path.join(bucket_dir, 'cibc.json'), 'localfilepath' : os.path.join(local_dir, 'cibc.json'), 'search': 'cibc'}
    files = []
    files.append(fileinfo)

    for f in files:
        #TODO: prevent copying if file already exists in /tmp
        _CopyFileFromBucket(f['bucketfilepath'], f['localfilepath'], '')
        SearchNewerTweets(f['localfilepath'], f['search'])
        _CopyFileToBucket(f['localfilepath'], f['bucketfilepath'], '') 

    return '200'


def _gcp_CopyFileFromBucket(srcfilepath, destfilepath, bucket):
    #TODO: error handling (log when file does not exist; but continue)
    blob = bucket.blob(srcfilepath)

    if blob.exists():
        blob.download_to_filename(destfilepath)

    return 0

def _gcp_CopyFileToBucket(srcfilepath, destfilepath, bucket):
    #TODO: error handling (log when file does not exist; but continue)
    blob = bucket.blob(destfilepath)
    blob.upload_from_filename(srcfilepath)
    return 0

def _CopyFileFromBucket(srcfilepath, destfilepath, bucket):
    #TODO: error handling (log when file does not exist; but continue)
    copyfile(srcfilepath, destfilepath)
    return 0

def _CopyFileToBucket(srcfilepath, destfilepath, bucket):
    #TODO: error handling (log when file does not exist; but continue)
    copyfile(srcfilepath, destfilepath)
    return 0

def SearchNewerTweets(filename_str, search_str):
	'''Searches for new tweets after the latest tweet present in the file.

    Since TWINT returns a limited and undefined number of tweets, there 
    is no guarantee that this results in a full file. Hence this would
    need to be run consistently and frequently to build histor.
    TODO: logic to ensure all tweets are obtained... (not worth it - only start from 'now'; history requires manual work)
	'''

	c = twint.Config()
	# choose username (optional)
	#c.Username = "insert username here"
	# choose search term (optional)
	c.Search = search_str
	# choose beginning time (narrow results)
	#c.Until = str(earliest_tweet_in_file())
	c.Since = str(latest_tweet_in_file(filename_str))
	# set limit on total tweets
	c.Limit = 2000 
	# no idea, but makes the csv format properly
	#c.Store_csv = True
	# format of the csv
	#c.Custom = ["date", "time", "username", "tweet", "link", "likes", "retweets", "replies", "mentions", "hashtags"]
	c.Store_json = True
	# change the name of the output file
	c.Output = filename_str
	c.Hide_output = True
	twint.run.Search(c)


def SearchEarlierTweets(filename_str, search_str):
    '''Searches for new tweets before the earliest tweet present in the file.'''
    c = twint.Config()
    c.Search = search_str
    c.Until = str(earliest_tweet_in_file(filename_str))
    c.Limit = 2000
    c.Store_json = True
    c.Output = filename_str
    c.Hide_output = True
    twint.run.Search(c) 

def latest_tweet_in_file(filename_str):
    #TODO: Rename to LatestTweetDateInFile
    _, result = _EarliestLatestTweetDateInFile(filename_str)
    return result

def earliest_tweet_in_file(filename_str):
    #TODO: Rename to EarliestTweetDateInFile
    result, _ = _EarliestLatestTweetDateInFile(filename_str)
    return result

def _EarliestLatestTweetDateInFile(filename_str):
    '''
    Given a file with tweets (as generated by TWINT), returns the datetime
    of the earliest and most recent tweet in the file.

    Note that a second is subtracted/added to this time.
    '''
    #TODO: not optimized
    #TODO: not sure of time zones are dealt with properly
    tweetsmetad = []
    latest_tweet_dt = datetime(1990, 5, 17) # arbitraty, but Twitter did not exist at this date
    earliest_tweet_dt = datetime.now()
    if os.path.isfile(filename_str): #only read file if it exists
        for line in open(filename_str, 'r', encoding="utf8"):
            tweetsmetad.append(json.loads(line))
            if datetime.strptime(tweetsmetad[-1]['created_at'], '%Y-%m-%d %H:%M:%S %Z')>latest_tweet_dt:
                latest_tweet_dt = datetime.strptime(tweetsmetad[-1]['created_at'], '%Y-%m-%d %H:%M:%S %Z')
            if datetime.strptime(tweetsmetad[-1]['created_at'], '%Y-%m-%d %H:%M:%S %Z')<earliest_tweet_dt:
                earliest_tweet_dt = datetime.strptime(tweetsmetad[-1]['created_at'], '%Y-%m-%d %H:%M:%S %Z')
            

    # adding 1 second (microseconds not captured at source) to avoid duplicates when searching using TWINT
    latest_tweet_dt = latest_tweet_dt + timedelta(0, 1, 0)

    earliest_tweet_dt = earliest_tweet_dt - timedelta(0, 1, 0)

    return earliest_tweet_dt, latest_tweet_dt

    
#################################################
#################################################
## Logic for Configuration file
#################################################
#################################################
def ReadConfigFileGCP():
    '''
    Reads the config file from Google Storage

    Returns the contents as a Python dictionary.
    '''
    CONFIG_FILE = 'configgcp.yaml'

    #TODO: use GCP credentials; would allow for local testing
    storage_client = storage.Client()
    bucketName = 'industrious-eye-330414.appspot.com'
    bucket = storage_client.get_bucket(bucketName)
    
    # TODO: Confirm file exists; or log error    
    blob = bucket.blob(CONFIG_FILE)
    data = blob.download_as_string(client=None)

    configdict = yaml.safe_load(data)

    return configdict


def ReadConfigFileLocal():
    ''' 
    Reads the config file from local storage

    Returns a dict with the contents of config file
    '''
    CONFIG_FILE = 'configgcp.yaml'

    # TODO: Confirm file exists
    with open(CONFIG_FILE, 'rt') as file:
        configdict = yaml.safe_load(file.read())

    return configdict

def ParseFilesFromConfig(configdict):
    '''
    Read file information from configgcp file
    
    arguments:
    - configdict: dictionary containing the configfile info

    Returns a list of dictionary values representing files to update with tweets
    and their search terms. 

    This function is indepenent of location of config file (cloud, local etc.)
    '''
    bucket_dir = os.path.join('')
    local_dir = os.path.join('/tmp')
    
    filesinfo = configdict.get('files', ['no files'])

    for f in filesinfo:
        f['bucketfilepath'] = os.path.join(bucket_dir, f.get('filename', 'nothing found in config file'))
        f['localfilepath'] = os.path.join(local_dir, f.get('filename', 'nothing found in config file'))
        f['historyfill'] = f.get('historyfill', False)

    return filesinfo

if __name__ == "__main__":
    # Used when running locally only. When deploying to Google App
    # Engine, a webserver process such as Gunicorn will serve the app. This
    # can be configured by adding an `entrypoint` to app.yaml.
    
    app.run(host="localhost", port=8080, debug=True)