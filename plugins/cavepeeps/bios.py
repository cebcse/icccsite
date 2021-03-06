from collections import namedtuple
import os
import re
import copy
import time

from olm.source import Source
from olm.logger import get_logger

logger = get_logger('olm.plugins.cavepeep')

def parse_metadata(metadata):
    metadata = [metadata] if not isinstance(metadata, list) else metadata
    c = re.compile(r"""\s*DATE=\s*(\d\d\d\d-\d\d-\d\d)\s*;\s*CAVE=\s*([\s\w\D][^;]*)\s*;\s*PEOPLE=\s*([\s\w\D][^;]*);*[\n\t\r]*""")
    people = []
    caves = []
    for entry in metadata:
            # Create key/value relationship between trip identifier (Date + Cave) and list of cavers
            item_caves = None
            item_people = None
            m = c.match(entry)
            try:
                item_caves=m.group(2)
                item_people=m.group(3).split(',')
            except AttributeError as e:
                logger.error("Error parsing metadata for caching")
                logger.error(e)
                continue
            people.extend([ p.strip() for p in item_people ])
            caves.extend([ c.strip() for c in item_caves.split('>')])
    return (people, caves)

def create_or_add(dictionary, key_to_add, data_to_add):
    if key_to_add in dictionary:
        dictionary[key_to_add] = dictionary[key_to_add] + data_to_add
    else:
        dictionary[key_to_add] = data_to_add

def construct_bios(sender, context, **kwargs):
    time_start = time.time()
    contentpath=context.SOURCE_FOLDER
    logger.debug("Cavebios starting")

    def get_bios(btype):
        path = os.path.join(contentpath, btype)
        dictionary = {}
        for dirpath, dirnames, filenames in os.walk(path):
            for afile in filenames:
                logger.debug("Cavebios: Reading {}/{}".format(dirpath, afile))
                article = Source(context, os.path.join(dirpath, afile))
                article = Source(context, os.path.join(dirpath, afile))
                article.data = get_data_from_metadata(article.metadata)
                article.cache_id = afile
                article.cache_type = btype.upper()
                context['all_files'].append(article)
                dictionary[os.path.splitext(afile)[0]]=article
        return dictionary

    context['caverbios']= get_bios("cavers")
    context['cavebios'] = get_bios("caves")
    logger.info("Processed cave and caver bios in %.3f seconds", (time.time() - time_start))

def get_data_from_metadata(metadata):
    data = {}
    for key in metadata.keys():
        if key == "location":
             data["map"] = """<div class="padmore"><iframe width="100%" height="450" frameborder="0" style="border:0" allowfullscreen src="https://www.google.com/maps/embed/v1/search?q=""" + re.sub(r',\s*', "%2C", metadata["location"].strip()) + """&maptype=satellite&key=AIzaSyB03Nzox4roDjtKoddF9xFcYsvm4vi26ig" allowfullscreen></iframe></div>"""
    return data

def was_author_in_cave(article, cave_name):
    if 'cavepeeps' not in article.article.metadata.keys():
        return False
    trips = article.article.metadata['cavepeeps']
    authors = []
    if 'author' in article.article.metadata.keys():
        authors = article.article.metadata['author']
    elif 'authors' in article.article.metadata.keys():
        authors = article.article.metadata['authors']
    for trip in trips:
        if cave_name in trip:
            for author in authors:
                if str(author) in trip:
                    return True
    return False

def generate_cave_pages(context, Writer):
    cave_bios  = context['cavebios']
    caves      = context['cavepeep_cave']
    caves_dict = {}

    # Split the through trips into individual caves.
    # Make unique list (set) of cave names and
    for trip in caves:
        for cave in trip.split('>'):
            create_or_add(caves_dict, cave.strip(), caves[trip])

    dictionary = caves_dict
    content_dictionary = cave_bios
    output_path = "caves"
    template = "cavepages"


    row = namedtuple('row', 'path content metadata articles same_as_cache')
    initialised_pages = {}

    for key in dictionary.keys():
        if key not in initialised_pages.keys():
            #logging.debug("Cavebios: Adding {} to list of pages to write".format(key))
            content=''
            metadata=''
            same_as_cache = False
            if key in content_dictionary:
                #logging.debug("Cavebios: Content added to " + key)
                content = content_dictionary[key].content
                metadata = content_dictionary[key].metadata
                same_as_cache = content_dictionary[key].same_as_cache
            else:
                same_as_cache = context.is_cached

            path= os.path.join(output_path, str(key) + '.html')
            initialised_pages[key]=(row(path, content, metadata, dictionary[key], same_as_cache))
        else:
            initialised_pages[key].articles.extend(dictionary[key])
    
    # Work out if we need to update this file
    changes = context['cache_change_types']
    meta_changes = context['cache_changed_meta']
    changed_caves = []
    if "ARTICLE.NEW_FILE" in changes or "ARTICLE.META_CHANGE" in changes:
        for meta_change in meta_changes:
            added, removed, modified = meta_change
            if 'cavepeeps' in added:
                people, caves = parse_metadata(added['cavepeeps'])
                changed_caves.extend(caves)
            if 'cavepeeps' in removed:
                people, caves = parse_metadata(removed['cavepeeps'])
                changed_caves.extend(caves)
            if 'cavepeeps' in modified:
                people, caves = parse_metadata(modified['cavepeeps'][0])
                changed_caves.extend(caves)
                people, caves = parse_metadata(modified['cavepeeps'][1])
                changed_caves.extend(caves)
    
    number_written = 0
    for page_name, page_data in initialised_pages.items():
        cave_articles = [ (a, a.date, was_author_in_cave(a, page_name)) for a in page_data.articles ]
        if page_data.same_as_cache and page_name not in changed_caves:
            continue
        number_written = number_written + 1
        writer = Writer(
            context, 
            page_data.path, 
            template + '.html',
            content=context.MD(page_data.content),
            metadata=page_data.metadata,
            cave_articles=sorted(cave_articles, key=lambda x: x[0].date, reverse=True),
            pagename=page_name)
        writer.write_file()
    logger.info("Wrote %s changed cave pages out of %s total cave pages", number_written, len(initialised_pages))
    # ==========Write the index of caves================
    logger.debug("writing %s cave pages", len(initialised_pages))
    pages = initialised_pages
    row=namedtuple('row', 'name number recentdate meta')
    rows = []
    for page_name in pages.keys():
        name = page_name
        number = len(pages[page_name].articles)
        recentdate = max([article.date for article in pages[page_name].articles])
        meta = content_dictionary[page_name].metadata if page_name in content_dictionary.keys() else None
        rows.append(row(name, number, recentdate, meta))
    filename=os.path.join(output_path, 'index.html')
    writer = Writer(
            context, 
            filename, 
            template + "_index.html",
            rows=sorted(rows, key=lambda x: x.name))
    writer.write_file()

def generate_person_pages(context, Writer):
    # For each person generate a page listing the caves they have been in and the article that
    # describes that trip
    author_list={}
    caver_bios=context['caverbios']
    cavers=context['cavepeep_person']

    dictionary = cavers
    content_dictionary = caver_bios
    output_path = "cavers"
    template = "caverpages"

    row = namedtuple('row', 'path content metadata articles authored same_as_cache')
    initialised_pages = {}

    for key in dictionary.keys():
        if key not in initialised_pages.keys():
            logger.debug("Adding {} to list of pages to write".format(key))
            content=''
            metadata=''
            authored=[]
            same_as_cache = False
            if key in content_dictionary:
                logger.debug("Content added to " + key)
                content = content_dictionary[key].content
                metadata = content_dictionary[key].metadata
                same_as_cache = content_dictionary[key].same_as_cache
            else:
                same_as_cache = context.is_cached
            if key in context.authors:
                authored = sorted(context.authors[key], key=lambda k: (k.date), reverse=True)
            path= os.path.join(output_path, str(key) + '.html')
            initialised_pages[key]=(row(path, content, metadata, dictionary[key], authored, same_as_cache))
        else:
            initialised_pages[key].articles.extend(dictionary[key])
    
    # Work out if we need to update this file
    changes = context['cache_change_types']
    meta_changes = context['cache_changed_meta']
    changed_people = []
    if "ARTICLE.NEW_FILE" in changes or "ARTICLE.META_CHANGE" in changes:
        for meta_change in meta_changes:
            added, removed, modified = meta_change
            if 'cavepeeps' in added:
                people, caves = parse_metadata(added['cavepeeps'])
                changed_people.extend(people)
            if 'cavepeeps' in removed:
                people, caves = parse_metadata(removed['cavepeeps'])
                changed_people.extend(people)
            if 'cavepeeps' in modified:
                people, caves = parse_metadata(modified['cavepeeps'][0])
                changed_people.extend(people)
                people, caves = parse_metadata(modified['cavepeeps'][1])
                changed_people.extend(people)

    logger.debug("writing %s caver pages", len(initialised_pages))
    number_written = 0
    for page_name, page_data in initialised_pages.items():
        if page_data.same_as_cache and page_name not in changed_people:
            continue
        number_written = number_written + 1
        writer = Writer(
            context, 
            page_data.path, 
            template + '.html',
            content=context.MD(page_data.content),
            metadata=page_data.metadata,
            caver_articles=sorted(page_data.articles, key=lambda x: x.date, reverse=True),
            personname=page_name,
            authored=page_data.authored)
        writer.write_file()
    pages = initialised_pages
    logger.info("Wrote %s changed caver pages out of %s total caver pages", number_written, len(initialised_pages))
    # ==========Write the index of cavers================
    row=namedtuple('row', 'name number recentdate meta')
    rows = []
    for page_name in pages.keys():
        name = page_name
        number = len(pages[page_name].articles)
        recentdate = max([article.date for article in pages[page_name].articles])
        meta = content_dictionary[page_name].metadata if page_name in content_dictionary.keys() else None
        rows.append(row(name, number, recentdate, meta))
    filename=os.path.join(output_path, 'index.html')
    writer = Writer(
        context, 
        filename, 
        template + "_index.html",
        rows=sorted(sorted(rows, key=lambda x: x.name), key=lambda x: x.recentdate, reverse=True))
    writer.write_file()

