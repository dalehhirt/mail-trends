#!/usr/bin/python

# Modified by Joao Paulo Barraca <jpbarraca@ua.pt>

import codecs
import getopt
import getpass
import logging
import messageinfo
import re
import sys

from Cheetah.Template import Template
import jwzthreading

import mail
import stats.base
import stats.bucket
import stats.group
import stats.table


def GetOptsMap():
    opts, args = getopt.getopt(sys.argv[1:], "", [
        # Standard options
        "username=", "password=", "use_ssl", "server=", "maildir=", "mailboxpackage=",

        # Other params
        "filter_out=", "me=", "server_mailbox=",

        # Development options
        "record", "replay",
        "max_messages=", "random_subset",
        "skip_labels",
        "is_gmail",
        "filter_labels="])

    if len(opts) == 0:
        print "Usage: main.py --username=<login> --password=<password> --server=<server_address> [options]"
        print "Main Parameters"
        print "\t--username=<login>\t\tThe login to use when connecting to the server"
        print "\t--password=<password>\t\tThe password to use when connecting to the server"
        print "\t--server=<server_address>\tThe IP address or DNS name of the server"
        print "\t--maildir=path\t\t\tRead emails from maildir folders"
        print "\t--mailboxpackage=path\t\tRead emails from mailbox packages (Mail.app)"
        print "\nOptions"
        print "\t--filter_out=<filter>\t\tRegular expression to filter results"
        print "\t--me=<address>\t\t\tYour email address"
        print "\t--use_ssl\t\t\tConnect to server using SSL"
        print "\t--server_mailbox=<inbox,mb1>\tOnly consider the given mailboxes (or label)"
        print "\t--is_gmail\tSet some common options for Gmail scanning. Auto-sets the server value, use_ssl, and filter_labels for [GMail] labels."
        print "\t--filter_labels=<inbox,label1>\tFilter out messages in the given mailboxes (or label)."
        print "\t                              \tPrepend a - to a label to not filter a specific label."
        print "\n"
        sys.exit()

    opts_map = {}
    for name, value in opts:
        opts_map[name[2:]] = value

    if "maildir" in opts_map:
        return opts_map

    if "mailboxpackage" in opts_map:
        return opts_map

    assert "username" in opts_map

    if "password" not in opts_map:
        opts_map["password"] = getpass.getpass(
            prompt="Password for %s: " % opts_map["username"])

    if "is_gmail" in opts_map:
      opts_map["server"]="imap.gmail.com"
      opts_map["use_ssl"]=""
      opts_map["server_mailbox"]="[Gmail]/All Mail"
      # Only if we are filtering at all, should we explicitly not filter these mailboxes.  We append, in case someone actually does want to do so
      gmail_filter="-[Gmail],-[Gmail]/All Mail,-[Gmail]/Chats,-[Gmail]/Drafts,-[Gmail]/Important,-[Gmail]/Sent Mail,-[Gmail]/Spam,-[Gmail]/Starred,-[Gmail]/Trash"
      if "filter_labels" in opts_map:
        opts_map["filter_labels"] =  gmail_filter + "," + opts_map["filter_labels"]

    print opts_map

    assert "password" in opts_map
    assert "server" in opts_map

    return opts_map

def FilterLabeledMessages(mailObj, filterLabels, messageInfos):
    logging.info("Filtering out labeled messages")

    # Don't want to parse all these dates, since we already have them from the
    # message infos above.
    messageinfo.MessageInfo.SetParseDate(False)
    mailboxes = mailObj.GetMailboxes()

    filtered_message_infos_ids = []
    message_infos_by_id = \
      dict([(mi.GetMessageId(), mi) for mi in messageInfos])
    
    filtered_mailboxes = mailboxes
    if len(filterLabels) != 0:
      filtered_labels = filterLabels.split(",")
      for filtered_label in filtered_labels:
        if filtered_label[0] == "-":
          real_label = filtered_label[1:]
          if real_label in filtered_mailboxes:
            filtered_mailboxes.remove(real_label)
        else:
          if not filtered_label in filtered_mailboxes:
            filtered_mailboxes.append(filtered_label)

    for mailbox in filtered_mailboxes:
      logging.info("Filtering mailbox '%s.'", mailbox)
      filtered_messages = 0
      mailObj.SelectMailbox(mailbox)
      message_ids = mailObj.GetMessageIds()
      for mid in message_ids:
        if ((mid in message_infos_by_id) and (not (mid in filtered_message_infos_ids))):
          filtered_message_infos_ids.append(mid)
          filtered_messages += 1
      logging.info("Filtered %d messages.", filtered_messages)
    
    filtered_messageinfos = []

    for mi in messageInfos:
      if not mi.GetMessageId() in filtered_message_infos_ids:
        filtered_messageinfos.append(mi)

    logging.info("Initial Message Count: %d", len(messageInfos))
    logging.info("Filtered Message Count: %d", len(filtered_messageinfos))

    return filtered_messageinfos

def GetMessageInfos(opts):

    if "maildir" in opts:
        m = mail.MaildirInfo(opts["maildir"])
    else:
        if "mailboxpackage" in opts:
            m = mail.MailBoxPackageInfo(opts["mailboxpackage"])
        else:
            m = mail.Mail(
                opts["server"], "use_ssl" in opts, opts[
                    "username"], opts["password"],
                "record" in opts, "replay" in opts,
                "max_messages" in opts and int(opts["max_messages"]) or -1,
                "random_subset" in opts,)

    message_infos = []
    server_mailbox = []
    if "server_mailbox" in opts:
        server_mailbox = opts['server_mailbox'].split(",")

    # Then for each mailbox, see which messages are in it, and attach that to
    # the mail info
    # if "skip_labels" not in opts:

        # Don't want to parse all these dates, since we already have them from the
        # message infos above.
    messageinfo.MessageInfo.SetParseDate(False)

    for mailbox in m.GetMailboxes():
        if len(server_mailbox) > 0:
            if mailbox not in server_mailbox:
                continue

        m.SelectMailbox(mailbox)
        mb_message_infos = m.GetMessageInfos()
        for message_info in mb_message_infos:
            message_info.AddMailbox(mailbox)
        message_infos.extend(mb_message_infos)
        logging.info("Mailbox had %d messages. Total=%d", len(
            mb_message_infos), len(message_infos))

    message_infos_by_id = dict(
        [(mi.GetMessageId(), mi) for mi in message_infos])
    messageinfo.MessageInfo.SetParseDate(True)

    if "filter_labels" in opts:
      message_infos = FilterLabeledMessages(m, opts["filter_labels"], message_infos)

    m.Logout()

    # Filter out those that we're not interested in
    if "filter_out" in opts:
        message_infos = FilterMessageInfos(message_infos, opts["filter_out"])

    # Tag messages as being from the user running the script
    if "me" in opts:
        logging.info("Identifying \"me\" messages")
        me_addresses = [address.lower().strip()
                        for address in opts["me"].split(",")]

        me_from_count = 0
        me_to_count = 0

        for message_info in message_infos:
            name, address = message_info.GetSender()

            for me_address in me_addresses:
                if me_address == address:
                    message_info.is_from_me = True
                    me_from_count += 1
                    break

            for name, address in message_info.GetRecipients():
                for me_address in me_addresses:
                    if me_address == address:
                        message_info.is_to_me = True
                        me_to_count += 1
                        break
                if message_info.is_to_me:
                    break

        logging.info("  %d messages are from \"me\"" % me_from_count)
        logging.info("  %d messages are to \"me\"" % me_to_count)

    return message_infos


def FilterMessageInfos(message_infos, filter_param):
    logging.info("Filtering messages")
    remaining_message_infos = []

    filters = []
    raw_filters = filter_param.split(",")
    for raw_filter in raw_filters:
        operator, value = raw_filter.strip().split(":", 1)
        filters.append([operator, value.lower()])

    for message_info in message_infos:
        filtered_out = False
        for operator, operator_value in filters:
            if operator == "to":
                pairs = message_info.GetRecipients()
            elif operator == "from":
                pairs = [message_info.GetSender()]
            elif operator == "list":
                pairs = [message_info.GetListId()]
            else:
                raise AssertionError("unknown operator: %s" % operator)

            values = [name and name.lower() or "" for name, address in pairs] + \
                [address and address.lower() or "" for name, address in pairs]

            for value in values:
                if value.find(operator_value) != -1:
                    filtered_out = True
                    break

            if filtered_out:
                break

        if not filtered_out:
            remaining_message_infos.append(message_info)

    logging.info("  %d messages remaining" % len(remaining_message_infos))
    return remaining_message_infos


def ExtractThreads(message_infos):
    thread_messages = []
    for message_info in message_infos:
        try:
            thread_message = jwzthreading.make_message(message_info.headers)
        except ValueError:
            continue

        if thread_message:
            thread_message.message_info = message_info
            thread_messages.append(thread_message)

    thread_dict = jwzthreading.thread(thread_messages)

    containers = []
    for subject, container in thread_dict.items():
        # jwzthreading is too aggressive in threading by subject and will combine
        # distinct threads that happen to have the same subject. Split them up if
        # we have a dummy container that has lots of children at the first
        # level.
        if container.is_dummy() and len(container.children) >= 10:
            for child_container in container.children:
                child_container.subject = subject
                containers.append(child_container)
        else:
            container.subject = subject
            containers.append(container)

    return containers


def InitStats(date_range):
    s = [
        stats.base.TitleStat(date_range),
        stats.group.StatTabGroup(
            (
                "Time",
                stats.group.StatColumnGroup(
                    stats.bucket.DayOfWeekStat(),
                    stats.bucket.TimeOfDayStat(),
                    stats.bucket.YearStat(date_range),
                ),
                stats.group.StatColumnGroup(
                    stats.group.MonthStatCollection(date_range),
                    stats.group.DayStatCollection(date_range),
                ),
            ),
            (
                "Size",
                stats.group.StatColumnGroup(
                    stats.bucket.SizeBucketStat(),
                    stats.table.SizeTableStat(),
                ),
            ),
            (
                "People and Lists",
                stats.group.StatColumnGroup(
                    stats.table.SenderTableStat(),
                    stats.group.SenderDistributionStatCollection(date_range),
                ),
                stats.group.StatColumnGroup(
                    stats.table.RecipientTableStat(),
                    stats.group.RecipientDistributionStatCollection(
                        date_range),
                ),
                stats.group.StatColumnGroup(
                    stats.table.ListIdTableStat(),
                    stats.group.ListDistributionStatCollection(date_range),
                ),
            ),
            (
                "Me",
                stats.group.StatColumnGroup(
                    stats.table.MeRecipientTableStat(),
                    stats.group.MeRecipientDistributionStatCollection(
                        date_range),
                ),
                stats.group.StatColumnGroup(
                    stats.table.MeSenderTableStat(),
                    stats.group.MeSenderDistributionStatCollection(date_range),
                ),
            ),
            (
                "Threads",
                stats.group.StatColumnGroup(
                    stats.bucket.ThreadSizeBucketStat(),
                    stats.table.ThreadSizeTableStat(),
                ),
                stats.group.StatColumnGroup(
                    stats.table.ThreadStarterTableStat(),
                    stats.table.ThreadListTableStat(),
                )
            )
        )
    ]

    return s

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

logging.info("Initializing")

opts = GetOptsMap()

message_infos = GetMessageInfos(opts)

logging.info("Extracting threads")
threads = ExtractThreads(message_infos)

stats = InitStats(messageinfo.MessageInfo.GetDateRange())

logging.info("Generating stats")

for stat in stats:
    stat.ProcessMessageInfos(message_infos, threads)

logging.info("Outputting HTML")

t = Template(
    file="templates/index.tmpl",
    searchList={
        "stats": stats,
        "host": re.sub("^.*@", "", opts.get("username", ''))
    }
)
out = codecs.open("out/index.html", mode="w", encoding='utf-8')
out.write(unicode(t))
out.close()

logging.info("Done")
