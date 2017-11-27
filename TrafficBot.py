import twitter
import sys
import os
import jinja2
import codecs
import locale
from datetime import date, datetime, timedelta
from subprocess import Popen, PIPE
from distutils.spawn import find_executable
from tempfile import NamedTemporaryFile
from io import BytesIO
from twitter.models import Status
from twitter.error import TwitterError
from requests.exceptions import ChunkedEncodingError
from configparser import SafeConfigParser, NoOptionError, NoSectionError
from PIL import Image

class tokenTwitter:
    def __init__(self, ckey='', csecret='', atoken='', asecret=''):
        self.consumer_key = ckey
        self.consumer_secret = csecret
        self.access_token_key = atoken
        self.access_token_secret = asecret

    def setToken(self, ckey, csecret, atoken, asecret):
        self.consumer_key = ckey
        self.consumer_secret = csecret
        self.access_token_key = atoken
        self.access_token_secret = asecret

    def setTokenFromFile(self, tfile):
        config = SafeConfigParser()
        if not config.read(tfile):
            print("Couldn't load configuration.")
            sys.exit(1)
        self.consumer_key = config.get('twitter_api', 'consumer_key')
        self.consumer_secret = config.get('twitter_api', 'consumer_secret')
        self.access_token_key = config.get('twitter_api', 'access_token_key')
        self.access_token_secret = config.get('twitter_api', 'access_token_secret')

    def configParam(self, tfile):
        config = SafeConfigParser()
        if not config.read(tfile):
            print("Couldn't load configuration.")
            sys.exit(1)
        return config

def apiFromConfig(token):
    api = twitter.Api(
        consumer_key = token.consumer_key,
        consumer_secret = token.consumer_secret,
        access_token_key = token.access_token_key,
        access_token_secret = token.access_token_secret,
        tweet_mode = 'extended')
    return api

def convertTruncated(tweet):
    raw_tweet = tweet._json
    if 'extended_tweet' in raw_tweet.keys():
        for key, value in raw_tweet['extended_tweet'].items():
            raw_tweet[key] = value
    converted_tweet = Status.NewFromJsonDict(raw_tweet)
    return converted_tweet

def processTweetText(tweet):
    text = tweet.full_text or tweet.text # protects against old clients
    for url in tweet.urls:
        text = text.replace(url.url, url.expanded_url)
    for media in tweet.media or []:
        text = text.replace(media.url, '')
    return jinja2.Markup(text.replace('\n', '<br>').strip())

def renderTweetHtml(tweet):
    date_format = '%A, %d %B, %Y %I:%M'
    context = {
        'body': processTweetText(tweet),
        'date': datetime.fromtimestamp(tweet.created_at_in_seconds).strftime(date_format),
        'account': tweet.user.screen_name
    }
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader('./')
    ).get_template('release_template.html').render(context)

def setTransparentPixel(image):
    pixel_location = (0,0)
    pixel_colour = (255,255,255,254) # nearly opaque white pixel
    image.putpixel(pixel_location, pixel_colour)
    return image

def htmlToPng(html):
    temp_file = '.temp.html'
    with open(temp_file, 'w') as f:
        f.write(html.encode('utf-8').decode('utf-8'))

    command = ['wkhtmltoimage']
    if not find_executable(command[0]):
        raise ImportError('%s not found' % command[0])

    command += ['-f', 'png'] # format output as PNG
    command += ['--zoom', '2'] # retina image
    command += ['--width', '750'] # viewport 750px wide
    command += [temp_file] # read from stdin
    command += ['-'] # write to stdout

    wkhtml_process = Popen(command, stdout=PIPE, stderr=PIPE)
    (output, err) = wkhtml_process.communicate()

    os.remove(temp_file)

    image = Image.open(BytesIO(output))
    image = setTransparentPixel(image)

    return image

def getStatusMessage(config):
    try:
        message = config.get('settings', 'message')
    except (NoOptionError, NoSectionError) as e:
        message = ''

    return message

def releaseTweet(tweet, api, config):
    if (tweet.truncated):
        tweet = convertTruncated(tweet)

    tweet_html = renderTweetHtml(tweet)
    image = htmlToPng(tweet_html)
    status = getStatusMessage(config) + ' @' + tweet.user.screen_name
    #print (status)
    media = []

    for media_item in tweet.media or []:
        extra_media_url = 'https://twitter.com/%s/status/%d' % (tweet.user.screen_name, tweet.id)
        if media_item.type == 'video':
            if status != '':
                status += '\n'
            status += '[Video: %s]' % extra_media_url

        elif media_item.type == 'animated_gif':
            if status != '':
                status += '\n'
            status += '[GIF: %s]' % extra_media_url

        elif media_item.type == 'photo':
            if len(media) < 3:
                media.append(media_item.media_url_https)

                # Use large photo size if available
                if 'large' in media_item.sizes:
                #if media_item.sizes.has_key('large'):
                    media[-1] += ':large'
            else:
                if status != '':
                    status += '\n'
                status += '[Photo: %s]' % extra_media_url

    print(status)
    print(media)

    with NamedTemporaryFile(suffix='.png') as png_file:
        image.save(png_file, format='PNG', dpi=(144,144))
        media.insert(0, png_file)
        api.PostUpdate(status=status, media=media)

def main():
    configFile = 'twitter_token.conf'
    locale.setlocale(locale.LC_ALL, "")
    tToken = tokenTwitter()
    tToken.setTokenFromFile(configFile)
    api = apiFromConfig(tToken)
    config = tToken.configParam(configFile)
    words_to_track = config.get('settings', 'words_to_track').split(',')
    try:
        for stream in api.GetStreamFilter(track= words_to_track):
            message = Status.NewFromJsonDict(stream)
            if (message.text[:2]!='RT'):
                releaseTweet(message,api,config)
    except (NoOptionError, NoSectionError) as e:
        stream = None


if __name__ == '__main__':
    main()
