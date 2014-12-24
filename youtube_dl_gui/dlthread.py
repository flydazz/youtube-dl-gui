#!/usr/bin/env python2

"""Youtubedlg module for managing the download process.

This module is responsible for managing the download process
and update the GUI interface.

Note:
    It's not the actual module that downloads the urls
    thats the job of the 'downloaders' module.
    
"""

import time
import os.path
from threading import Thread

from wx import CallAfter
from wx.lib.pubsub import setuparg1
from wx.lib.pubsub import pub as Publisher

from .parsers import OptionsParser
from .updthread import UpdateThread
from .downloaders import YoutubeDLDownloader

from .utils import YOUTUBEDL_BIN


class DownloadManager(Thread):
    
    """Manages the download process.
    
    Attributes:
        PUBLISHER_TOPIC (string): Subscription topic for the wx Publisher.
        WORKERS_NUMBER (int): Size of custom thread pool.
        WAIT_TIME (float): Time in seconds to sleep.
    
    Args:
        urls_list (list): Python list that contains multiple dictionaries
            with the url to download and the corresponding row(index) in
            which the worker should send the download process information.
        
        opt_manager (optionsmanager.OptionsManager): Object responsible for
            managing the youtubedlg options.
            
        log_manager (logmanager.LogManager): Object responsible for writing
            erros to the log.
        
    """
    
    PUBLISHER_TOPIC = 'dlmanager'
    WORKERS_NUMBER = 3
    WAIT_TIME = 0.1
    
    def __init__(self, urls_list, opt_manager, log_manager=None):
        super(DownloadManager, self).__init__()
        self.opt_manager = opt_manager
        self.log_manager = log_manager
        self.urls_list = urls_list
        
        self._time_it_took = 0
        self._successful = 0
        self._running = True
        
        self._workers = self._init_workers()
        self.start()
    
    @property
    def successful(self):
        """Return number of successful downloads. """
        return self._successful
        
    @property
    def time_it_took(self):
        """Return time in seconds it took for the 
        download process to finish.
        
        """
        return self._time_it_took
        
    def increase_succ(self):
        """Increase number of successful downloads. """
        self._successful += 1
    
    def run(self):
        self._check_youtubedl()
        self._time_it_took = time.time()
        
        while self._running:
            for worker in self._workers:
                if worker.available() and self.urls_list:
                    worker.download(self.urls_list.pop(0))
            
            time.sleep(self.WAIT_TIME)
            
            if not self.urls_list and self._jobs_done():
                break
                
        # Clean up
        for worker in self._workers:
            worker.close()
            worker.join()
            
        self._time_it_took = time.time() - self._time_it_took
        
        if not self._running:
            self._talk_to_gui('closed')
        else:
            self._talk_to_gui('finished')
                
    def active(self):
        """Return number of active items.
        active_items = workers that work + items waiting in the url_list.
        
        """
        counter = 0
        for worker in self._workers:
            if not worker.available():
                counter += 1
                
        counter += len(self.urls_list)
        
        return counter
    
    def stop_downloads(self):
        """Stop the download process. Also send 'closing' 
        signal back to the GUI.
        
        Note:
            It does NOT kill the workers thats the job of the 
            clean up task in the run() method.
            
        """
        self._talk_to_gui('closing')
        self._running = False
        for worker in self._workers:
            worker.stop_download()
    
    def add_url(self, url):
        """Add given url to the urls_list.
        
        Args:
            url (dictionary): Python dictionary that contains two keys,
                the url and the index of the corresponding row
                to send the download information back.
        
        """
        self.urls_list.append(url)
    
    def _talk_to_gui(self, data):
        """Send data back to the GUI using wx CallAfter and wx Publisher. 
        
        Args:
            data (string): Unique signal string that informs the GUI for the
                download process.
                
        Note:
            DownloadManager supports 3 signals for the moment.
                1) closing: The download process is closing.
                2) closed: The download process has closed.
                3) finished: The download process terminated normally.
        
        """
        CallAfter(Publisher.sendMessage, self.PUBLISHER_TOPIC, data)
    
    def _check_youtubedl(self):
        """Check if youtube-dl binary exists. If not try to download it. """
        if not os.path.exists(self._youtubedl_path()):
            UpdateThread(self.opt_manager.options['youtubedl_path'], True).join()
    
    def _jobs_done(self):
        """Return True if the workers have finished their jobs. 
        Else return False.
        
        """
        for worker in self._workers:
            if not worker.available():
                return False
                
        return True
    
    def _youtubedl_path(self):
        """Return the path of the youtube-dl binary. """
        path = self.opt_manager.options['youtubedl_path']
        path = os.path.join(path, YOUTUBEDL_BIN)
        return path
    
    def _init_workers(self):
        """Initialise the custom thread pool.
        
        Returns:
            Python list that contains the workers.
        
        """ 
        youtubedl = self._youtubedl_path()
        return [Worker(self.opt_manager, youtubedl, self.increase_succ, self.log_manager) for i in xrange(self.WORKERS_NUMBER)]

        
class Worker(Thread):
    
    """Simple worker that downloads the given url using a downloader.
    
    Attributes:
        PUBLISHER_TOPIC (string): Subscription topic for the wx Publisher.
        WAIT_TIME (float): Time in seconds to sleep.
    
    Args:
        opt_manager (optionsmanager.OptionsManager): Check DownloadManager
            description.
            
        youtubedl (string): Absolute path to youtube-dl binary.
        
        increase_succ (DownloadManager.increase_succ() method): Callback to
            increase the number of successful downloads.
            
        log_manager (logmanager.LogManager): Check DownloadManager
            description.
    
    """
    
    PUBLISHER_TOPIC = 'dlworker'
    WAIT_TIME = 0.1
    
    def __init__(self, opt_manager, youtubedl, increase_succ, log_manager=None):
        super(Worker, self).__init__()
        self.increase_succ = increase_succ
        self.opt_manager = opt_manager
        
        self._downloader = YoutubeDLDownloader(youtubedl, self._data_hook, log_manager)
        self._options_parser = OptionsParser()
        self._running = True
        self._url = None
        self._index = -1
        
        self.start()
        
    def run(self):
        while self._running:
            if self._url is not None:
                options = self._options_parser.parse(self.opt_manager.options)             
                ret_code = self._downloader.download(self._url, options)
            
                if (ret_code == YoutubeDLDownloader.OK or
                        ret_code == YoutubeDLDownloader.ALREADY):
                    self.increase_succ()
                
                # Reset
                self._url = None
            
            time.sleep(self.WAIT_TIME)
    
    def download(self, item):
        """Download given item.
        
        Args:
            item (dictionary): Python dictionary that contains two keys,
                the url and the index of the corresponding row
                to send the download information back.
        
        """
        self._url = item['url']
        self._index = item['index']
    
    def stop_download(self):
        """Stop the download process of the worker. """
        self._downloader.stop()
    
    def close(self):
        """Kill the worker after stopping the download process. """
        self._running = False
        self._downloader.stop()
    
    def available(self):
        """Return True if the worker has no job. Else False. """
        return self._url is None
    
    def _data_hook(self, data):
        """Callback method.
        
        This method takes the data from the downloader, merges the 
        playlist_info with the current status (if any) and sends the
        data back to the GUI.
        
        Args:
            data (dictionary): Python dictionary that contains information
                about the download process. (See YoutubeDLDownloader class).
        
        """
        if data['status'] is not None and data['playlist_index'] is not None:
            playlist_info = ' '
            playlist_info += data['playlist_index']
            playlist_info += '/'
            playlist_info += data['playlist_size']
                
            data['status'] += playlist_info

        self._talk_to_gui(data)
    
    def _talk_to_gui(self, data):
        """Send the data back to the GUI after inserting the index. """
        data['index'] = self._index
        CallAfter(Publisher.sendMessage, self.PUBLISHER_TOPIC, data)

        
if __name__ == '__main__':
    """Direct call of module for testing.
    
    Raises:
        ValueError: Attempted relative import in non-package
    
    Note:
        Before you run the tests change relative imports else an exceptions
        will be raised. You need to change relative imports on all the modules
        you are gonna use.
    
    """
    print "No tests available"
        
