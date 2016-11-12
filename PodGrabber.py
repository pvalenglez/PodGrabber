#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import urllib2
import xml.dom.minidom
import datetime
import calendar
from time import gmtime, strftime, strptime, mktime
import sqlite3
import shutil
import smtplib
import platform
import traceback
import httplib
from urlparse import urlparse
import codecs
from subprocess import call


def strict_handler(exception):
    return u"", exception.end
codecs.register_error("strict", strict_handler)


MODE_NONE = 70
MODE_SUBSCRIBE = 71
MODE_DOWNLOAD = 72
MODE_UNSUBSCRIBE = 73
MODE_LIST = 74
MODE_UPDATE = 75
MODE_MAIL_ADD = 76
MODE_MAIL_DELETE = 77
MODE_MAIL_LIST = 78
MODE_EXPORT = 79
MODE_IMPORT = 80

NUM_MAX_DOWNLOADS = 999999

DOWNLOAD_DIRECTORY = "podcasts"

# Added 2011-10-06 Werner Avenant - added current_dictory here so it can be global
current_directory = ''
m3u_file = ''

total_item = 0
total_size = 0


def main():
    mode = MODE_NONE
    has_error = 0
    error_string = ""
    feed_url = ""
    mail_address = ""
    email = ""
    # Added 2011-10-06 Werner Avenant
    global current_directory
    global m3u_file
    now = datetime.datetime.now()
    m3u_file = str(now)[:10] + '.m3u'
    current_directory = os.path.realpath(os.path.dirname(sys.argv[0]))
    download_directory = current_directory + os.sep + DOWNLOAD_DIRECTORY

    global total_items
    global total_size
    total_items = 0
    total_size = 0
    data = ""

    parser = argparse.ArgumentParser(description='A command line Podcast downloader for RSS XML feeds')
    parser.add_argument('-s', '--subscribe', action="store", dest="sub_feed_url",
                        help='Subscribe to the following XML feed and download latest podcast')
    parser.add_argument('-d', '--download', action="store", dest="dl_feed_url",
                        help='Bulk download all podcasts in the following XML feed or file')
    parser.add_argument('-un', '--unsubscribe', action="store", dest="unsub_url",
                        help='Unsubscribe from the following Podcast feed')
    parser.add_argument('-ma', '--mail-add', action="store", dest="mail_address_add",
                        help='Add a mail address to mail subscription updates to')
    parser.add_argument('-md', '--mail-delete', action="store", dest="mail_address_delete",
                        help='Delete a mail address')

    parser.add_argument('-l', '--list', action="store_const", const="ALL", dest="list_subs",
                        help='Lists current Podcast subscriptions')
    parser.add_argument('-u', '--update', action="store_const", const="UPDATE", dest="update_subs",
                        help='Updates all current Podcast subscriptions')
    parser.add_argument('-ml', '--mail-list', action="store_const", const="MAIL", dest="list_mail",
                        help='Lists all current mail addresses')

    parser.add_argument('-io', '--import', action="store", dest="opml_import",
                        help='Import subscriptions from OPML file')
    parser.add_argument('-eo', '--export', action="store_const", const="OPML_EXPORT", dest="opml_export",
                        help='Export subscriptions to OPML file')

    arguments = parser.parse_args()

    if arguments.sub_feed_url:
        feed_url = arguments.sub_feed_url
        data = open_datasource(feed_url)
        if not data:
            error_string = "Not a valid XML file or URL feed!"
            has_error = 1
        else:
            print "XML data source opened\n"
            mode = MODE_SUBSCRIBE

    elif arguments.dl_feed_url:
        feed_url = arguments.dl_feed_url
        data = open_datasource(feed_url)
        if not data:
            error_string = "Not a valid XML file or URL feed!"
            has_error = 1
        else:
            print "XML data source opened\n"
            mode = MODE_DOWNLOAD

    elif arguments.unsub_url:
        feed_url = arguments.unsub_url
        mode = MODE_UNSUBSCRIBE

    elif arguments.list_subs:
        mode = MODE_LIST

    elif arguments.update_subs:
        mode = MODE_UPDATE

    elif arguments.mail_address_add:
        mail_address = arguments.mail_address_add
        mode = MODE_MAIL_ADD

    elif arguments.mail_address_delete:
        mail_address = arguments.mail_address_delete
        mode = MODE_MAIL_DELETE

    elif arguments.list_mail:
        mode = MODE_MAIL_LIST

    elif arguments.opml_import:
        import_file_name = arguments.opml_import
        mode = MODE_IMPORT

    elif arguments.opml_export:
        mode = MODE_EXPORT

    else:
        error_string = "No Arguments supplied - for usage run 'PodGrab.py -h'"
        has_error = 1

    print "Default encoding: " + sys.getdefaultencoding()
    todays_date = strftime("%a, %d %b %Y %H:%M:%S", gmtime())
    print "Current Directory: ", current_directory
    if does_database_exist(current_directory):
        connection = connect_database(current_directory)
        if not connection:
            error_string = "Could not connect to PodGrab database file!"
            has_error = 1
        else:
            cursor = connection.cursor()
    else:
        print "PodGrab database missing. Creating..."
        connection = connect_database(current_directory)
        if not connection:
            error_string = "Could not create PodGrab database file!"
            has_error = 1
        else:
            print "PodGrab database created"
            cursor = connection.cursor()
            setup_database(cursor, connection)
            print "Database setup complete"

    if not os.path.exists(download_directory):
        print "Podcast download directory is missing. Creating..."
        try:
            os.mkdir(download_directory)
            print "Download directory '" + download_directory + "' created"
        except OSError:
            error_string = "Could not create podcast download sub-directory!"
            has_error = 1
    else:
        print "Download directory exists: '" + download_directory + "'"
    if not has_error and "cursor" in locals() and ("import_file_name" in locals() if mode == MODE_IMPORT else 1):
        if mode == MODE_UNSUBSCRIBE:
            feed_name = get_name_from_feed(cursor, feed_url)
            if feed_name == "None":
                print "Feed does not exist in the database! Skipping..."
            else:
                feed_name = clean_string(feed_name)
                channel_directory = download_directory + os.sep + feed_name
                print "Deleting '" + channel_directory + "'..."
                delete_subscription(cursor, connection, feed_url)
                try:
                    shutil.rmtree(channel_directory)
                except OSError:
                    print "Subscription directory has not been found - it might have been manually deleted"
                print "Subscription '" + feed_name.encode('utf8') + "' removed"
        elif mode == MODE_LIST:
            print "Listing current podcast subscriptions...\n"
            list_subscriptions(cursor)
        elif mode == MODE_UPDATE:
            print "Updating all podcast subscriptions..."
            subs = get_subscriptions(cursor)
            for sub in subs:
                feed_name = sub[0]
                feed_url = sub[1]
                print "Feed for subscription: '" + feed_name.encode('utf8') + "' from '" + feed_url.encode('utf8') \
                    + "' is updating..."
                data = open_datasource(feed_url)
                if not data:
                    print "'" + feed_url + "' for '" + feed_name.encode('utf8') + "' is not a valid feed URL!"
                else:
                    message = iterate_feed(data, mode, download_directory, todays_date, cursor, connection, feed_url)
                    print message
                    email += message
            email = email + "\n\n" + str(total_items) + " podcasts totalling " + bytesto(total_size, 'm') \
                + " megabytes have been downloaded."
            if has_mail_users(cursor):
                print "Have e-mail address(es) - attempting e-mail..."
                mail_updates(cursor, email, str(total_items))
        elif mode == MODE_DOWNLOAD or mode == MODE_SUBSCRIBE:
            print iterate_feed(data, mode, download_directory, todays_date, cursor, connection, feed_url)
        elif mode == MODE_MAIL_ADD:
            add_mail_user(cursor, connection, mail_address)
            print "E-Mail address: " + mail_address + " has been added"
        elif mode == MODE_MAIL_DELETE:
            delete_mail_user(cursor, connection, mail_address)
            print "E-Mail address: " + mail_address + " has been deleted"
        elif mode == MODE_MAIL_LIST:
            list_mail_addresses(cursor)
        elif mode == MODE_EXPORT:
            export_opml_file(cursor, current_directory)
        elif mode == MODE_IMPORT:
            import_opml_file(cursor, connection, current_directory, download_directory, import_file_name)
    else:
        print "Sorry, there was some sort of error: '" + error_string + "'\nExiting...\n"
        if connection:
            connection.close()


def bytesto(sizeinbytes, to, bsize=1024):
    """convert bytes to megabytes, etc.
       sample code:
           print('mb= ' + str(bytesto(314575262000000, 'm')))

       sample output:
           mb= 300002347.946
    """

    a = {'k': 1, 'm': 2, 'g': 3, 't': 4, 'p': 5, 'e': 6}
    r = float(sizeinbytes)
    for i in range(a[to]):
        r /= bsize

    return "{0:.2f}".format(r)


def open_datasource(xml_url):
    try:
        response = urllib2.urlopen(xml_url.encode('utf-8'))
    except ValueError:
        try:
            response = open(xml_url.encode('utf-8'), 'r')
        except ValueError:
            print "ERROR - Invalid feed!"
            response = False
    except urllib2.URLError:
        print "ERROR - Connection problems. Please try again later"
        response = False
    except httplib.IncompleteRead:
        print "ERROR - Incomplete data read. Please try again later"
        response = False
    if response:
        return response.read()
    else:
        return response


def export_opml_file(cur, cur_dir):
    item_count = 0
    now = datetime.datetime.now()
    file_name = cur_dir + os.sep + "podgrab_subscriptions-" + str(now.year) + "-" + str(now.month) + "-" + str(
        now.day) + ".opml"
    subs = get_subscriptions(cur)
    file_handle = open(file_name.encode('utf-8'), "w")
    print "Exporting RSS subscriptions database to: '" + file_name + "' OPML file...please wait.\n"
    header = "<opml version=\"2.0\">\n<head>\n\t<title>PodGrab Subscriptions</title>\n</head>\n<body>\n"
    file_handle.writelines(header)
    for sub in subs:
        feed_name = sub[0]
        feed_url = sub[1]
        file_handle.writelines(
            "\t<outline title=\"" + feed_name + "\" text=\"" + feed_name + "\" type=\"rss\" xmlUrl=\"" + feed_url +
            "\" htmlUrl=\"" + feed_url + "\"/>\n")
        print "Exporting subscription '" + feed_name + "'...Done.\n"
        item_count += 1
    footer = "</body>\n</opml>"
    file_handle.writelines(footer)
    file_handle.close()
    print str(item_count) + " item(s) exported to: '" + file_name + "'. COMPLETE"


def import_opml_file(cur, conn, cur_dir, download_dir, import_file):
    count = 0
    print "Importing OPML file '" + import_file + "'..."
    if import_file.startswith("/") or import_file.startswith(".."):
        data = open_datasource(import_file)
        if not data:
            print "ERROR = Could not open OPML file '" + import_file + "'"
    else:
        data = open_datasource(cur_dir + os.sep + import_file)
        if not data:
            print "ERROR - Could not open OPML file '" + cur_dir + os.sep + import_file + "'"
    if data:
        print "File opened...please wait"
        try:
            xml_data = xml.dom.minidom.parseString(data)
            items = xml_data.getElementsByTagName('outline')
            for item in items:
                item_feed = item.getAttribute('xmlUrl')
                item_name = item.getAttribute('title')
                item_name = clean_string(item_name)
                print "Subscription Title: " + item_name
                print "Subscription Feed: " + item_feed
                item_directory = download_dir + os.sep + item_name

                if not os.path.exists(item_directory):
                    os.makedirs(item_directory)
                if not does_sub_exist(cur, item_feed):
                    insert_subscription(cur, conn, item_name, item_feed)
                    count += 1
                else:
                    print "This subscription is already present in the database. Skipping..."
                print "\n"
            print "\nA total of " + str(count) + " subscriptions have been added from OPML file: '" + import_file + "'"
            print "These will be updated on the next update run.\n"
        except xml.parsers.expat.ExpatError:
            print "ERROR - Malformed XML syntax in feed. Skipping..."


def iterate_feed(data, mode, download_dir, today, cur, conn, feed):
    print "Iterating feed..."
    message = ""
    try:
        xml_data = xml.dom.minidom.parseString(data)

        if len(xml_data.getElementsByTagName('channel')) != 0:
            for channel in xml_data.getElementsByTagName('channel'):
                channel_title = channel.getElementsByTagName('title')[0].firstChild.data
                channel_link = channel.getElementsByTagName('link')[0].firstChild.data
                print "Channel Title: ===" + channel_title + "==="
                print "Channel Link: " + channel_link
                channel_title = clean_string(channel_title)

                channel_directory = download_dir + os.sep + channel_title
                if not os.path.exists(channel_directory):
                    os.makedirs(channel_directory)
                print "Current Date: ", today
                if mode == MODE_DOWNLOAD:
                    print "Bulk download. Processing..."
                    # 2011-10-06 Replaced channel_directory with channel_title - needed for m3u file later
                    num_podcasts = iterate_channel(channel, mode, cur, conn, feed, channel_title)
                    print "\n", num_podcasts, "have been downloaded"
                elif mode == MODE_SUBSCRIBE:
                    print "Feed to subscribe to: " + feed + ". Checking for database duplicate..."
                    if not does_sub_exist(cur, feed):
                        print "Subscribe. Processing..."
                        # 2011-10-06 Replaced channel_directory with channel_title - needed for m3u file later
                        num_podcasts = iterate_channel(channel, mode, cur, conn, feed, channel_title)

                        print "\n", num_podcasts, "have been downloaded from your subscription"
                    else:
                        print "Subscription already exists! Skipping..."
                elif mode == MODE_UPDATE:
                    print "Updating RSS feeds. Processing..."
                    num_podcasts = iterate_channel(channel, mode, cur, conn, feed, channel_title)
                    message += str(num_podcasts) + " have been downloaded from your subscription: '" + channel_title + "'\n"
        else:
            print "THIS IS A YOUTUBE FEED\n"
            for channel in xml_data.getElementsByTagName('feed'):
                channel_title = channel.getElementsByTagName('title')[0].firstChild.data
                channel_link = channel.getElementsByTagName('link')[0].attributes.items()[0][1]
                print "Channel Title: ===" + channel_title + "==="
                print "Channel Link: " + channel_link
                channel_title = clean_string(channel_title)

                channel_directory = download_dir + os.sep + channel_title
                if not os.path.exists(channel_directory):
                    os.makedirs(channel_directory)
                print "Current Date: ", today
                if mode == MODE_DOWNLOAD:
                    print "Bulk download. Processing..."
                    # 2011-10-06 Replaced channel_directory with channel_title - needed for m3u file later
                    num_podcasts = iterate_channel(channel, mode, cur, conn, feed, channel_title)
                    print "\n", num_podcasts, "have been downloaded"
                elif mode == MODE_SUBSCRIBE:
                    print "Feed to subscribe to: " + feed + ". Checking for database duplicate..."
                    if not does_sub_exist(cur, feed):
                        print "Subscribe. Processing..."
                        # 2011-10-06 Replaced channel_directory with channel_title - needed for m3u file later
                        num_podcasts = iterate_channel(channel, mode, cur, conn, feed, channel_title)

                        print "\n", num_podcasts, "have been downloaded from your subscription"
                    else:
                        print "Subscription already exists! Skipping..."
                elif mode == MODE_UPDATE:
                    print "Updating RSS feeds. Processing..."
                    num_podcasts = iterate_channel(channel, mode, cur, conn, feed, channel_title)
                    message += str(num_podcasts) + " have been downloaded from your subscription: '" + channel_title + "'\n"

    except xml.parsers.expat.ExpatError:
        print "ERROR - Malformed XML syntax in feed. Skipping..."
        message += "0 podcasts have been downloaded from this feed (" \
            + ") due to RSS syntax problems. Please try again later\n"
    except UnicodeEncodeError:
        print "ERROR - Unicoce encoding error in string. Cannot convert to ASCII. Skipping..."
        message += "0 podcasts have been downloaded from this feed (" \
            + ") due to RSS syntax problems. Please try again later\n"
    return message


def clean_string(string):
    new_string = string
    if new_string.startswith("-"):
        new_string = new_string.lstrip("-")
    if new_string.endswith("-"):
        new_string = new_string.rstrip("-")
    new_string_final = ''
    for c in new_string:
        if c.isalnum() or c == "-" or c == "." or c.isspace():
            new_string_final += ''.join(c)
            new_string_final = new_string_final.replace(' ', '_')
            new_string_final = new_string_final.replace('---', '_')
            new_string_final = new_string_final.replace('--', '_')
            new_string_final = new_string_final.replace(u"á", "a")
            new_string_final = new_string_final.replace(u"Á", "A")
            new_string_final = new_string_final.replace(u"é", "e")
            new_string_final = new_string_final.replace(u"É", "E")
            new_string_final = new_string_final.replace(u"í", "i")
            new_string_final = new_string_final.replace(u"Í", "I")
            new_string_final = new_string_final.replace(u"ó", "o")
            new_string_final = new_string_final.replace(u"Ó", "O")
            new_string_final = new_string_final.replace(u"ú", "u")
            new_string_final = new_string_final.replace(u"Ú", "U")
            new_string_final = new_string_final.replace(u"ñ", "n")
            new_string_final = new_string_final.replace(u"Ñ", "N")

    return new_string_final


# Change 2011-10-06 - Changed chan_loc to channel_title to help with relative path names
# in the m3u file
def write_podcast(item, channel_title, date, filetype, item_title):

    local_file = current_directory + os.sep + DOWNLOAD_DIRECTORY + os.sep + channel_title + os.sep + clean_string(
        item_title)
    if filetype == "video/quicktime" or filetype == "audio/mp4" or filetype == "video/mp4":
        if not local_file.endswith(".mp4"):
            local_file += ".mp4"

    elif filetype == "video/mpeg":
        if not local_file.endswith(".mpg"):
            local_file += ".mpg"

    elif filetype == "video/x-flv":
        if not local_file.endswith(".flv"):
            local_file += ".flv"

    elif filetype == "video/x-ms-wmv":
        if not local_file.endswith(".wmv"):
            local_file += ".wmv"

    elif filetype == "video/webm" or filetype == "audio/webm":
        if not local_file.endswith(".webm"):
            local_file += ".webm"

    elif filetype == "audio/mpeg":
        if not local_file.endswith(".mp3"):
            local_file += ".mp3"

    elif filetype == "audio/ogg" or filetype == "video/ogg" or filetype == "audio/vorbis":
        if not local_file.endswith(".ogg"):
            local_file += ".ogg"
    elif filetype == "audio/x-ms-wma" or filetype == "audio/x-ms-wax":
        if not local_file.endswith(".wma"):
            local_file += ".wma"
    elif filetype == "application/x-shockwave-flash":
        if not local_file.endswith(".youtube"):
            local_file += ".youtube"
    else:
        local_file += os.path.splitext(urlparse(item).path)[1]

    # Check if file exists, but if the file size is zero (which happens when the user
    # presses Crtl-C during a download) - the the code should go ahead and download
    # as if the file didn't exist
    if os.path.exists(local_file) and os.path.getsize(local_file) != 0:
        return 'File Exists'
    else:
        print "\nDownloading " + item_title.encode('utf8') + " which was published on " + date
        if local_file.endswith(".youtube"):
            print "YouTUBE download"
            local_file = local_file.replace(".youtube", ".m4a")
            print ("/usr/bin/youtube-dl -o \"" + local_file + "\" -f 140 " + item)
            call(["/usr/bin/youtube-dl", "-f", "140", item, "-o", local_file])
            call(["/usr/bin/ffmpeg", "-i", local_file, "-vn", "-q:a", "8", "-ac", "1", local_file.replace(".m4a", ".mp3")])
            call(["rm", local_file])
            local_file = local_file.replace(".m4a", ".mp3")

            try:
                    os.utime(local_file.encode('utf-8'),
                             (calendar.timegm(datetime.datetime.strptime(date[:-6], '%a, %d %b %Y %X').utctimetuple()),
                              calendar.timegm(datetime.datetime.strptime(date[:-6], '%a, %d %b %Y %X').utctimetuple())))
            except Exception:
                    try:
                        os.utime(local_file.encode('utf-8'),
                             (calendar.timegm(datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S').utctimetuple()),
                              calendar.timegm(datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S').utctimetuple())))
                    except Exception:
                        os.utime(local_file.encode('utf-8'),
                             (calendar.timegm(datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z").utctimetuple()),
                              calendar.timegm(datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z").utctimetuple())))
            print "Podcast: ", item, " downloaded to: ", local_file
            # 2011-11-06 Append to m3u file
            output = open(current_directory + os.sep + m3u_file, 'a')
            path_split = local_file.split("/")
            path_split.reverse()
            output.write(DOWNLOAD_DIRECTORY + os.sep + channel_title.encode('utf8') + os.sep +
            path_split[0].encode('utf8') + "\n")
            output.close()
            return 'Successful Write'
        else:
            try:
                item_file = urllib2.urlopen(item)
                output = open(local_file.encode('utf-8'), 'wb')
                # 2011-10-06 Werner Avenant - For some reason the file name changes when
                # saved to disk - probably a python feature (sorry, only wrote my first line of python today)
                item_file_name = os.path.basename(output.name)
                output.write(item_file.read())
                output.close()

                call(["/usr/bin/ffmpeg", "-i", local_file, "-vn", "-q:a", "8", "-ac", "1", local_file.replace(".mp3", "_1.mp3")])
                call(["rm", local_file])
                call(["mv", local_file.replace(".mp3", "_1.mp3"), local_file])
                local_file = local_file.replace("_1.mp3", ".mp3")

                try:
                    os.utime(local_file.encode('utf-8'),
                             (calendar.timegm(datetime.datetime.strptime(date[:-6], '%a, %d %b %Y %X').utctimetuple()),
                              calendar.timegm(datetime.datetime.strptime(date[:-6], '%a, %d %b %Y %X').utctimetuple())))
                except Exception:
                    try:
                        os.utime(local_file.encode('utf-8'),
                             (calendar.timegm(datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S').utctimetuple()),
                              calendar.timegm(datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S').utctimetuple())))
                    except Exception:
                        os.utime(local_file.encode('utf-8'),
                             (calendar.timegm(datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z").utctimetuple()),
                              calendar.timegm(datetime.datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %Z").utctimetuple())))
                print "Podcast: ", item, " downloaded to: ", local_file
                # 2011-11-06 Append to m3u file
                output = open(current_directory + os.sep + m3u_file, 'a')
                output.write(DOWNLOAD_DIRECTORY + os.sep + channel_title.encode('utf8') + os.sep +
                             item_file_name.encode('utf8') + "\n")
                output.close()
                return 'Successful Write'
            except urllib2.URLError as e:
                print "ERROR - Could not write item to file: ", e
                return 'Write Error'


def does_database_exist(curr_loc):
    db_name = "PodGrab.db"
    if os.path.exists(curr_loc + os.sep + db_name):
        return 1
    else:
        return 0


def add_mail_user(cur, conn, address):
    row = (address,)
    cur.execute('INSERT INTO email(address) VALUES (?)', row)
    conn.commit()


def delete_mail_user(cur, conn, address):
    row = (address,)
    cur.execute('DELETE FROM email WHERE address = ?', row)
    conn.commit()


def get_mail_users(cur):
    cur.execute('SELECT address FROM email')
    return cur.fetchall()


def list_mail_addresses(cur):
    cur.execute('SELECT * from email')
    result = cur.fetchall()
    print "Listing mail addresses..."
    for address in result:
        print "Address:\t" + address[0]


def has_mail_users(cur):
    cur.execute('SELECT COUNT(*) FROM email')
    if cur.fetchone() == "0":
        return 0
    else:
        return 1


def mail_updates(cur, mess, num_updates):
    addresses = get_mail_users(cur)
    for address in addresses:
        try:
            subject_line = "PodGrab Update"
            if int(num_updates) > 0:
                subject_line += " - NEW updates!"
            else:
                subject_line += " - nothing new..."
            mail('smtp.googlemail.com', 'noreply@podgrab.com' + platform.node(), address[0], subject_line, mess)
            print "Successfully sent podcast updates e-mail to: " + address[0]
        except smtplib.SMTPException:
            traceback.print_exc()
            print "Could not send podcast updates e-mail to: " + address[0]


def mail(server_url='', sender='', to='', subject='', text=''):
    headers = "From: %s\r\nTo: %s\r\nSubject: %s\r\n\r\n" % (sender, to, subject)
    message = headers + text
    mail_server = smtplib.SMTP(server_url)
    mail_server.ehlo()
    mail_server.starttls()
    mail_server.ehlo()
    mail_server.login('email', 'password')
    mail_server.sendmail(sender, to, message.encode("utf-8"))
    mail_server.quit()


def connect_database(curr_loc):
    conn = sqlite3.connect(curr_loc + os.sep + "PodGrab.db")
    return conn


def setup_database(cur, conn):
    cur.execute("CREATE TABLE subscriptions (channel text, feed text, last_ep text)")
    cur.execute("CREATE TABLE email (address text)")
    conn.commit()


def insert_subscription(cur, conn, chan, feed):
    chan.replace(' ', '-')
    chan.replace('---', '-')
    # Added a correctly formatted date here so we can avoid an ugly "if date == null" in update_subscription later
    row = (chan, feed, "Thu, 01 Jan 1970 00:00:00")
    cur.execute('INSERT INTO subscriptions(channel, feed, last_ep) VALUES (?, ?, ?)', row)
    conn.commit()


def iterate_channel(chan, mode, cur, conn, feed, channel_title):
    global total_items
    global total_size
    num = 0
    size = 0
    size_subscription = 0
    print "Iterating channel..."

    if does_sub_exist(cur, feed):
        print "Podcast subscription exists"

    else:
        print "Podcast subscription is new - getting previous podcast"
        insert_subscription(cur, conn, chan.getElementsByTagName('title')[0].firstChild.data, feed)

    last_ep = get_last_subscription_downloaded(cur, feed)

    # NB NB - The logic here is that we get the "last_ep" before we enter the loop
    # The result is that it allows the code to "catch up" on missed episodes because
    # we never update the "last_ep" while inside the loop.
    if len(chan.getElementsByTagName('item')) != 0:
        for item in chan.getElementsByTagName('item'):
            try:
                item_title = item.getElementsByTagName('title')[0].firstChild.data
                item_date = item.getElementsByTagName('pubDate')[0].firstChild.data
                item_file = item.getElementsByTagName('enclosure')[0].getAttribute('url')
                item_size = item.getElementsByTagName('enclosure')[0].getAttribute('length')
                item_type = item.getElementsByTagName('enclosure')[0].getAttribute('type')

                try:
                    struct_time_item = strptime(fix_date(item_date), "%a, %d %b %Y %H:%M:%S")

                    try:
                        struct_last_ep = strptime(last_ep, "%a, %d %b %Y %H:%M:%S")

                        if mktime(struct_time_item) > mktime(struct_last_ep) or mode == MODE_DOWNLOAD:
                            saved = write_podcast(item_file, channel_title, item_date, item_type, item_title)

                            if saved == 'File Exists':
                                print "File Existed - updating local database's Last Episode"
                                update_subscription(cur, conn, feed, fix_date(item_date))

                            if saved == 'Successful Write':
                                print "\nTitle: " + item_title
                                print "Date:  " + item_date
                                print "File:  " + item_file
                                local_file = current_directory + os.sep + DOWNLOAD_DIRECTORY + os.sep + channel_title \
                                    + os.sep + clean_string(item_title)

                                type = item_type

                                if type == "video/quicktime" or type == "audio/mp4" or type == "video/mp4":
                                    if not local_file.endswith(".mp4"):
                                        local_file += ".mp4"

                                elif type == "video/mpeg":
                                    if not local_file.endswith(".mpg"):
                                        local_file += ".mpg"

                                elif type == "video/x-flv":
                                    if not local_file.endswith(".flv"):
                                        local_file += ".flv"

                                elif type == "video/x-ms-wmv":
                                    if not local_file.endswith(".wmv"):
                                        local_file += ".wmv"

                                elif type == "video/webm" or type == "audio/webm":
                                    if not local_file.endswith(".webm"):
                                        local_file += ".webm"

                                elif type == "audio/mpeg":
                                    if not local_file.endswith(".mp3"):
                                        local_file += ".mp3"

                                elif type == "audio/ogg" or type == "video/ogg" or type == "audio/vorbis":
                                    if not local_file.endswith(".ogg"):
                                        local_file += ".ogg"
                                elif type == "audio/x-ms-wma" or type == "audio/x-ms-wax":
                                    if not local_file.endswith(".wma"):
                                        local_file += ".wma"
                                else:
                                    local_file = local_file + os.path.splitext(urlparse(item_file).path)[1]

                                print "Size:  " + bytesto(os.stat(local_file).st_size, 'm') + " megabytes"
                                print "Type:  " + item_type
                                update_subscription(cur, conn, feed, fix_date(item_date))
                                num += 1
                                if item_size != '':
                                    size = os.stat(local_file).st_size

                                size_subscription += size
                                total_items += 1

                            # In subscribe mode we only want 1 this loop to execute 15 times
                            if (mode == MODE_SUBSCRIBE) and (total_items == 15):
                                break

                            if num >= NUM_MAX_DOWNLOADS:
                                print "Maximum session download of " + str(
                                    NUM_MAX_DOWNLOADS) + " podcasts has been reached. Exiting."
                                break
                        else:
                            print "According to database we already have the episode dated " + item_date
                            break

                    except TypeError:
                        print "This item has a badly formatted date. Cannot download!"
                    except ValueError:
                        print "This item has a badly formatted date. Cannot download!"

                except TypeError:
                    print "This item has a badly formatted date. Cannot download!"
                except ValueError:
                    print "This item has a badly formatted date. Cannot download!"

            except IndexError:
                # traceback.print_exc()
                print "This RSS item has no downloadable URL link for the podcast for '" \
                      + chan.getElementsByTagName('title')[0].firstChild.data + "'. Skipping..."

        total_size += size_subscription
        return str(num) + " podcasts totalling " + bytesto(size_subscription, 'm') + " megabytes"
    else:
        for item in chan.getElementsByTagName('entry'):
            try:
                item_title = item.getElementsByTagName('title')[0].firstChild.data
                item_date = item.getElementsByTagName('published')[0].firstChild.data
                item_date = item_date.split('+')[0]
                item_file = item.getElementsByTagName('media:content')[0].getAttribute('url')
                item_size = 0
                type = item.getElementsByTagName('media:content')[0].getAttribute('type')

                try:
                    struct_time_item = strptime(item_date, "%Y-%m-%dT%H:%M:%S")

                    try:
                        struct_last_ep = strptime(last_ep, "%Y-%m-%dT%H:%M:%S")
                    except Exception:
                        struct_last_ep = strptime(last_ep, "%a, %d %b %Y %H:%M:%S")

                    try:
                        if mktime(struct_time_item) > mktime(struct_last_ep) or mode == MODE_DOWNLOAD:
                            saved = write_podcast(item_file, channel_title, item_date, type, item_title)

                            if saved == 'File Exists':
                                print "File Existed - updating local database's Last Episode"
                                update_subscription(cur, conn, feed, fix_date(item_date))

                            if saved == 'Successful Write':
                                print "\nTitle: " + item_title
                                print "Date:  " + item_date
                                print "File:  " + item_file
                                local_file = current_directory + os.sep + DOWNLOAD_DIRECTORY + os.sep + channel_title \
                                    + os.sep + clean_string(item_title)

                                if type == "video/quicktime" or type == "audio/mp4" or type == "video/mp4":
                                    if not local_file.endswith(".mp4"):
                                        local_file += ".mp4"

                                elif type == "video/mpeg":
                                    if not local_file.endswith(".mpg"):
                                        local_file += ".mpg"

                                elif type == "video/x-flv":
                                    if not local_file.endswith(".flv"):
                                        local_file += ".flv"

                                elif type == "video/x-ms-wmv":
                                    if not local_file.endswith(".wmv"):
                                        local_file += ".wmv"

                                elif type == "video/webm" or type == "audio/webm":
                                    if not local_file.endswith(".webm"):
                                        local_file += ".webm"

                                elif type == "audio/mpeg":
                                    if not local_file.endswith(".mp3"):
                                        local_file += ".mp3"

                                elif type == "audio/ogg" or type == "video/ogg" or type == "audio/vorbis":
                                    if not local_file.endswith(".ogg"):
                                        local_file += ".ogg"
                                elif type == "audio/x-ms-wma" or type == "audio/x-ms-wax":
                                    if not local_file.endswith(".wma"):
                                        local_file += ".wma"
                                elif type == "application/x-shockwave-flash":
                                    if not local_file.endswith(".mp3"):
                                        local_file += ".mp3"
                                else:
                                    local_file = local_file + os.path.splitext(urlparse(item_file).path)[1]

                                print "Size:  " + bytesto(os.stat(local_file).st_size, 'm') + " megabytes"
                                print "Type:  " + type
                                update_subscription(cur, conn, feed, item_date)
                                num += 1
                                if item_size != '':
                                    size = os.stat(local_file).st_size

                                size_subscription += size
                                total_items += 1

                            # In subscribe mode we only want 1 this loop to execute 15 times
                            if (mode == MODE_SUBSCRIBE) and (total_items == 15):
                                break

                            if num >= NUM_MAX_DOWNLOADS:
                                print "Maximum session download of " + str(
                                    NUM_MAX_DOWNLOADS) + " podcasts has been reached. Exiting."
                                break
                        else:
                            print "According to database we already have the episode dated " + item_date
                            break

                    except TypeError:
                        print "This item has a badly formatted date. Cannot download!"
                    except ValueError:
                        print "This item has a badly formatted date. Cannot download!"

                except TypeError:
                    print "This item has a badly formatted date. Cannot download!"
                except ValueError:
                    print "This item has a badly formatted date. Cannot download!"

            except IndexError:
                traceback.print_exc()
                print "This RSS item has no downloadable URL link for the podcast for '" \
                      + chan.getElementsByTagName('title')[0].firstChild.data + "'. Skipping..."

        total_size += size_subscription
        return str(num) + " podcasts totalling " + bytesto(size_subscription, 'm') + " megabytes"

def fix_date(date):
    new_date = ""
    split_array = date.split(' ')
    for i in range(0, 5):
        new_date = new_date + split_array[i] + " "
    return new_date.rstrip()


def does_sub_exist(cur, feed):
    row = (feed,)
    cur.execute('SELECT COUNT (*) FROM subscriptions WHERE feed = ?', row)
    return_string = str(cur.fetchone())[1]
    if return_string == "0":
        return 0
    else:
        return 1


def delete_subscription(cur, conn, url):
    row = (url,)
    cur.execute('DELETE FROM subscriptions WHERE feed = ?', row)
    conn.commit()


def get_name_from_feed(cur, url):
    row = (url,)
    cur.execute('SELECT channel from subscriptions WHERE feed = ?', row)
    return_string = cur.fetchone()
    try:
        return_string = ''.join(return_string)
    except TypeError:
        return_string = "None"
    return str(return_string)


def list_subscriptions(cur):
    count = 0
    try:
        result = cur.execute('SELECT * FROM subscriptions')
        for sub in result:
            print "Name:\t\t", sub[0]
            print "Feed:\t\t", sub[1]
            print "Last Ep:\t", sub[2], "\n"
            count += 1
        print str(count) + " subscriptions present"
    except sqlite3.OperationalError:
        print "There are no current subscriptions or there was an error"


def get_subscriptions(cur):
    try:
        cur.execute('SELECT * FROM subscriptions')
        return cur.fetchall()
    except sqlite3.OperationalError:
        print "There are no current subscriptions"
        return


def update_subscription(cur, conn, feed, date):
    # Make sure that the date we are trying to write is newer than the last episode
    # Presumes that "null" dates will be saved in DB as 1970-01-01 (unix "start" time)
    existing_last_ep = get_last_subscription_downloaded(cur, feed)

    try:
        if mktime(strptime(existing_last_ep, "%a, %d %b %Y %H:%M:%S")) <= mktime(strptime(date, "%a, %d %b %Y %H:%M:%S")):
            row = (date, feed)
            cur.execute('UPDATE subscriptions SET last_ep = ? where feed = ?', row)
            conn.commit()
    except Exception:
        try:

            if mktime(strptime(existing_last_ep, '%a, %d %b %Y %H:%M:%S')) <= mktime(strptime(date, '%Y-%m-%dT%H:%M:%S')):
                row = (date, feed)
                cur.execute('UPDATE subscriptions SET last_ep = ? where feed = ?', row)
                conn.commit()
        except Exception:
            if mktime(strptime(existing_last_ep, '%Y-%m-%dT%H:%M:%S')) <= mktime(strptime(date, '%Y-%m-%dT%H:%M:%S')):
                row = (date, feed)
                cur.execute('UPDATE subscriptions SET last_ep = ? where feed = ?', row)
                conn.commit()

def get_last_subscription_downloaded(cur, feed):
    row = (feed,)
    cur.execute('SELECT last_ep FROM subscriptions WHERE feed = ?', row)
    rec = cur.fetchone()
    return rec[0]


if __name__ == "__main__":
    main()