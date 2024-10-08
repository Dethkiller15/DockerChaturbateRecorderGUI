#base
from django.core.management.base import BaseCommand, CommandError

from utils.adapter.adapter_factory import AdapterFactory

#utils
import os, subprocess
import re
import requests
from django.template.defaultfilters import slugify

#models and manager
from models.wishlistItem import WishlistItem


# import the logging library
import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    containerPrefix = os.environ['CONTAINER_PREFFIX']
    adapter_factory = AdapterFactory()

    def stopAllChannels(self):
        logger.debug('call stopAllChannels')

        items = WishlistItem.unmanaged_objects.filter(type='c', status=1)
        for item in items:
            slug = slugify(item.title)
            containerName = str(self.containerPrefix + slug)
            item.status = 0
            item.save()
            self.stopContainer(containerName)



        
    def stopContainer(self, containerName):
        logger.debug('call stopContainer ' + containerName)

        command = self.adapter_factory.create_adapter(os.environ['COMMAND_ADAPTER']).stopInstance(containerName)
        logger.debug('- call command ' + command)

        return subprocess.Popen(
            command, 
            shell=True, 
            stdout=subprocess.PIPE,
            close_fds=True
        )

    def deletedChannels(self):
        logger.debug('call deletedChannels')
        deleted_items = WishlistItem.unmanaged_objects.filter(type='c', deleted=1).order_by('-prio')
        for item in deleted_items:
            slug = slugify(item.title)
            containerName = str(self.containerPrefix + slug)
            self.stopContainer(containerName)
            item.delete()

    def getInstances(self):
        logger.debug('call getInstances')

        command = self.adapter_factory.create_adapter(os.environ['COMMAND_ADAPTER']).getInstances(self.containerPrefix)
        logger.debug('- call command ' + command)

        containers = subprocess.run(
            command, 
            shell=True, 
            stdout=subprocess.PIPE
        ).stdout.decode().splitlines()
        return containers


    def checkChannels(self):
        logger.debug('call checkChannels')
        containers = self.getInstances()

        items = WishlistItem.unmanaged_objects.filter(type='c', deleted=0).order_by('-prio')

        for item in items:

            slug = slugify(item.title)
            containerName = str(self.containerPrefix + slug)
            logger.debug('- check ' + containerName)

            if containerName in containers:
                item.status = 1
                item.save()
                logger.debug('- status run')

            else:
                logger.debug('- status dead')
                if int(os.environ['LIMIT_MAXIMUM_DOWNLOADS']) != 0 and len(containers) > int(os.environ['LIMIT_MAXIMUM_DOWNLOADS']):
                    break


                # Form the URL using the title
                url = str("https://chaturbate.com/" + slug)

                # Fetch the HTML content from the URL
                response = requests.get(url)
                html_content = response.text

                # Find all occurrences of URLs ending with .m3u8
                streams = re.findall(r'https://[a-zA-Z0-9.+-_:/]*\.m3u8', html_content)

                if streams:
                        stream = re.sub(r'\\u([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), streams[0])
                        
                        command = self.adapter_factory.create_adapter(os.environ['COMMAND_ADAPTER']).startInstance(
                                os.environ['ABSOLUTE_HOST_MEDIA'], 
                                containerName, 
                                stream,
                                int(os.environ['LIMIT_MAXIMUM_FOLDER_GB']),
                                os.environ['RECORDER_IMAGE'],
                                os.environ['USER_UID'],
                                os.environ['USER_GID'],
                                item.resolution
                            )

                        container = subprocess.Popen(
                            command,
                            shell=True, 
                            stdin=None, 
                            stdout=None, 
                            stderr=None,
                            close_fds=True
                        )

                        logger.debug('- call command ' + command)
                else:
                    logger.debug('- channel ' + slug + ' is offline')
                if item.status == 1:
                    item.status = 0
                    item.save()

    def checkFilter(self):
        logger.debug('call checkFilter')
        containers = self.getInstances()
        delta = 1024

        if int(os.environ['LIMIT_MAXIMUM_DOWNLOADS']) != 0: 
            delta = int(os.environ['LIMIT_MAXIMUM_DOWNLOADS']) - len(containers)

        if delta == 0:
            return False
        
        items = WishlistItem.unmanaged_objects.filter(type='f', deleted=0).order_by('-prio')
            
        for item in items:
            url = 'https://chaturbate.com/api/ts/roomlist/room-list/?offset=0&limit=' + str(delta)

            if item.age != 'all':
                url += '&ages=' + item.age
            elif item.region != 'all':
                url += '&regions=' + item.region
            else:
                url += '&hashtags=' + item.title
   


            #https://chaturbate.com/api/ts/roomlist/room-list/?genders=m&limit=90&offset=0


            if item.gender == 'w':
                url += '&genders=w'
            elif item.gender == 'm':
                url += '&genders=m'
            elif item.gender == 'c':
                url += '&genders=c'
            elif item.gender == 't':
                url += '&genders=t'


            logger.debug('- curl url ' + url)

            r = requests.get(url)
            data = r.json()

            for channel in data['rooms']:
                logger.debug(channel)
  
                logger.debug('- find channel' + channel['username'])
                WishlistItem.unmanaged_objects.get_or_create(
                    title = channel['username'],
                    type = 'c',
                    prio = item.prio,
                    resolution = item.resolution
                )

    def deleteFilter(self):
        logger.debug('call deleteFilter')
        WishlistItem.unmanaged_objects.filter(type='f', deleted=1).delete()

    def handle(self, *args, **options):
        logger.debug('call handle')
        PROJECT_ROOT = os.path.realpath(os.path.dirname(__file__))
        videoDir = os.path.join(PROJECT_ROOT, '../../../media/videos')

        self.checkChannels()

        self.deletedChannels()
        self.checkFilter()
        self.deleteFilter()
