import re, hikari, lightbulb, requests, json, pickle, logging, mysql.connector

from HackNottsVerification.bot import Bot
from datetime import datetime

# Update this with the HackNotts server ID's
server_info = {
    'server_id': 1023695785495363584,
    'verified': 1025399005477343323,
    'attendee': 1025399116706095198,
    'volunteer': 1025896388048977921,
    'sponsor': 1026621003171897404
} # Role ID's

def update_ticket_data():
    # SQL database info
    with open("./secrets/tito", "r") as file: # reads the private file for the API Token
        tito_token = file.read().strip()

    with open("./secrets/sqlserver_pass", "r") as file:
        sql_pass = file.read().strip()

    with open("./secrets/sqlserver_user", "r") as file:
        sql_user = file.read().strip()

    try:
        db = mysql.connector.connect(
        host="localhost",
        user=sql_user,
        password=sql_pass,
        database="HackNotts"
        )
        db_cursor = db.cursor()
    except mysql.connector.errors.DatabaseError:
        logging.warning("Cannot connect to database")
        return None

    # Tito data stuff
    account_slug = "olivermalkin"
    event_slug = "test"
    question_slug = "what-is-your-discord-tag"

    try:
        with open("./HackNottsVerification/bot/extensions/last_time.pkl", "rb") as file:
            last_time = pickle.load(file)
    except FileNotFoundError:
        last_time = None

    with open("./HackNottsVerification/bot/extensions/last_time.pkl", "wb") as file:
        pickle.dump(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+UTC"), file=file) # Dumps the time stamp to a file

    updates = 0 # Number of updates
    page = 1
    loop = True
    while loop:
        if last_time is None:
            url = f'https://api.tito.io/v3/{account_slug}/{event_slug}/tickets?page[100]={page}&expand=responses,release&search[direction]=desc&search[states][]=complete'
        else:
            url = f'https://api.tito.io/v3/{account_slug}/{event_slug}/tickets?page[100]={page}&expand=responses,release&search[direction]=desc&search[states][]=complete&search[updated_at][gte]={last_time}'

        header = {'Authorization': f'Token token={tito_token}', 'Accept': 'application/json'}
        tito_data = json.loads(requests.get(url, headers=header).text)

        number = len(tito_data['tickets'])
        for ticket in range(number):
            try:
                discord_tag = tito_data['tickets'][ticket]['responses'][question_slug]
            except KeyError:
                discord_tag = None

            ticket_ref  = tito_data['tickets'][ticket]['reference']
            ticket_type = tito_data['tickets'][ticket]['release']['title'].lower()

            if discord_tag is not None:
                sql = f"INSERT INTO `People` (`DiscordTag`, `TicketRef`, `TicketType`) VALUES ('{discord_tag}', '{ticket_ref}', '{ticket_type}')"
            else:
                sql = f"INSERT INTO `People` (`TicketRef`, `TicketType`) VALUES ('{ticket_ref}', '{ticket_type}')"

            try:
                db_cursor.execute(sql)
                db.commit()
                updates += 1
            except mysql.connector.errors.IntegrityError:
                # Update discord tag
                sql = f"UPDATE `People` SET `DiscordTag` = '{discord_tag}' WHERE `TicketRef` = '{ticket_ref}'"
                db_cursor.execute(sql)
                db.commit()

        if tito_data['meta']['next_page'] is None:
            loop = False
        else:
            page += 1

    logging.info(f"Updates were triggered: {updates} updates pushed to the database. Time: {last_time}") # Adds a log
    db.close()
    return updates # How many tickets were there to update
        

def user_verify(user, ref):
    ref = ref.upper()
    with open("./secrets/sqlserver_pass", "r") as file:
        sql_pass = file.read().strip()

    with open("./secrets/sqlserver_user", "r") as file:
        sql_user = file.read().strip()

    try:

        db = mysql.connector.connect(
        host="localhost",
        user=sql_user,
        password=sql_pass,
        database="HackNotts"
        )
    except mysql.connector.DatabaseError:
        return None

    db_cursor = db.cursor()
    sql = f"SELECT `ID`, `DiscordTag`, `TicketType`, `Verified` FROM `People` WHERE `TicketRef` = '{ref.upper()}'"
    db_cursor.execute(sql)
    try:
        result = db_cursor.fetchall()[0]
    except IndexError:
        result = None

    flag = 0 # Have they tried using someone elses code
    verif = False
    if result is None: # There was no reference found
        message = f"The ticket reference '**{ref}**' does not seem to be in our database. Please check you have entered it correctly. It should be 6 characters ***including*** the hyphen"
    elif result[3] == 1 and str(result[1]) == str(user): # The verified tag is 1 and the discord tags match
        message = f"You are already verified!"
    elif result[3] == 1: # Verified is 1 but discord tags dont match
        message = f"It appears that the ticket with reference '**{ref}**' is already registered with a user. A message has been automatically sent to an organiser who will contact you shortly to resolve this issue"
        flag = 1
    elif result[1] is not None: # There is something in the discord tag
        if str(result[1]) == str(user): # Verified is not 1 and tags match
            verif = True
        else:
            message = f"There is a linked Discord Tag to this ticket reference '{ref}' which does not match yours. If you entered your Discord tag when assigning your ticket, double check that it has both the username and the discriminator e.g `JoeBloggs#1234`. If it does not match then you will not be able to verify yourself. You can update your information via the ticket confirmation email."
            flag = 2
    elif result[1] is None: # There is no discord tag so must be verified
        verif = True

    if verif is True: # Verify user and update record
        try:
            sql = f"UPDATE `People` SET `Verified` = 1, `DiscordTag` = '{user}' WHERE `ID` = {result[0]}" # Set user to be verified and set their tag
            db_cursor.execute(sql)
            db.commit()

            logging.info(f"User '{user}' has been verified with as '{ref}'")
            message = f"You have been verified with ticket type: **{result[2]}** and have accompanying role assigned to you. Thank you!"

        except mysql.connector.errors.IntegrityError: # Probably a discord tag is in the database
            message = f"Your Discord tag is already assigned to a ticket reference. A message has been sent to an organiser and will be with you to resolve this issue"
            flag = 3

    db.close()

    try:
        return (message, flag, str(result[2])) # Message is the text that the person will see as an ephemeral
    except TypeError:
        return(message, flag, None)

def auto_verify(tag):
    with open("./secrets/sqlserver_pass", "r") as file:
        sql_pass = file.read().strip()

    with open("./secrets/sqlserver_user", "r") as file:
        sql_user = file.read().strip()

    try:
        db = mysql.connector.connect(
        host="localhost",
        user=sql_user,
        password=sql_pass,
        database="HackNotts"
        )
    except mysql.connector.DatabaseError:
        return (None, None, None)

    db_cursor = db.cursor()
    sql = f"SELECT `ID`, `TicketRef`, `TicketType`, `Verified` FROM `People` WHERE `DiscordTag` = '{tag}'"
    db_cursor.execute(sql)
    try:
        result = db_cursor.fetchall()[0]
    except IndexError:
        result = None

    _type = None
    _id = None
    flag = False # Used if they join and their discord tag is already verified
    if result is None:
        flag = None # Don't do anything 
    elif result[3] == 1:
        flag = True
    else:
        sql = f"UPDATE `People` SET `Verified` = 1, `DiscordTag` = '{tag}' WHERE `ID` = {result[0]}" # Set user to be verified and set their tag
        _id = result[0]
        db_cursor.execute(sql)
        db.commit()

        logging.info(f"User: {tag} has been auto verified as '{result[2]}'")
        _type = str(result[2])

    db.close()
    return (flag, _id, _type) # Is the person already verified?

plugin = lightbulb.Plugin("verify")

@plugin.listener(hikari.MemberCreateEvent)
async def on_join(event: hikari.MemberCreateEvent) -> None:
    if not event.member.is_bot and not event.member.is_system:
        update_ticket_data()
        logging.info(f"User: {event.user.username}#{event.member.discriminator} joined the server")
        result = auto_verify(f"{event.user.username}#{event.member.discriminator}")

        flag = result[0]
        ticket_type = result[2]

        if flag is True: # User already registered
            me = await event.app.rest.create_dm_channel(427401640061042689)
            await me.send(f"The user <@{event.user_id}> joined HackNotts server but was already verified")

            message = f"Hello! Thank you for joining the HackNotts '23 Discord server. It appears that your Discord tag is already verified on our database, this means you will not be able to send messages in the server. An organiser will be in contact shortly to resolve this issue :smile:"
            logging.warning(f"User: {event.user.username}#{event.member.discriminator} joined the server but was already verifed?")
        elif flag is False: # Autoverification worked
            message = f"Hello! This is an automatic notification to say you have been verified on the HackNotts '23 Discord server. This is because you entered your Discord tag when assigning your ticket. Please have a look around and introduce yourself!"
            await event.app.rest.add_role_to_member(server_info['server_id'], event.user_id, server_info['verified'])   # adds verified role
            await event.app.rest.add_role_to_member(server_info['server_id'], event.user_id, server_info[ticket_type])  # adds either volunteer or attendee role
        elif flag is None: # Just a join
            pass

        if flag is not None:
            user = await event.app.rest.create_dm_channel(event.user_id)
            await user.send(message)
        elif result[0] is None:
            me = await event.app.rest.create_dm_channel(427401640061042689)
            me.send("The MySQL server is down")
    else:
        logging.info(f"Bot: {event.user.username}#{event.member.discriminator} joined the server")

@plugin.command
@lightbulb.add_checks(lightbulb.human_only)
@lightbulb.option("ticket", "Your 6 character ticket ID \"1234-5\", case insensitive")
@lightbulb.command("verify", "This is used to manually verify yourself, if auto verification doesn't work", auto_defer=True, ephemeral=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def verify_command(ctx: lightbulb.SlashContext) -> None:
    if re.search('^[-A-Za-z0-9]+$', ctx.options.ticket) is not None:
        update_ticket_data() # Ensure database it up-to-date
        message = user_verify(ctx.author, ctx.options.ticket) # Returns the response and flag

        error = None
        if message is None:
            error = "The MySQL server is down"
            message = ("An internal error has occured. Please try again in a few minutes", None)
        elif message[1] == 1: # The verified flag is true
            error = f"The user <@{ctx.author.id}> tried verifying with ticket reference '{ctx.options.ticket.upper()}' but it is already verified"
        elif message[1] == 2: # They used one with a discord tag already filled in but isnt verified
            error = f"The user <@{ctx.author.id}> tried verifying with ticket reference '{ctx.options.ticket.upper()}' but the discord tags did not match"
        elif message[1] == 3:
            error = f"The user <@{ctx.author.id}> tried verifying with ticket reference '{ctx.options.ticket.upper()}' but their discord tag is already registered to a ticket reference"

        if error is not None: # Is there an error?
            logging.warning(error)
            me = await ctx.bot.rest.create_dm_channel(427401640061042689)
            await me.send(error) # Send me an error via a DM
        else:
            if message[2] is not None: # Is there a role to assign? if none then that means that the ticket ref was not found
                await ctx.app.rest.add_role_to_member(server_info['server_id'], ctx.user.id, server_info['verified'])    # adds verified role
                await ctx.app.rest.add_role_to_member(server_info['server_id'], ctx.user.id, server_info[message[2]])    # adds either volunteer or attendee role

        await ctx.respond(message[0])
    else:
        await ctx.respond("The ticket can only contain letters, numbers and hyphens")

@plugin.command
@lightbulb.add_checks(lightbulb.owner_only)
@lightbulb.command("update", "Manually syncs the database to ticket data if needed (do not spam)", auto_defer=True, ephemeral=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def update_command(ctx: lightbulb.SlashContext) -> None:
    updates = update_ticket_data()
    if updates is None:
        await ctx.respond("Cannot reach mysql server!")
    elif updates == 0:
        await ctx.respond("There were zero updates")
    elif updates == 1:
        await ctx.respond("There was 1 update")
    else:
        await ctx.respond(f"There were {updates} updates")

def load(bot: Bot) -> None:
    bot.add_plugin(plugin)

def unload(bot: Bot) -> None:
    bot.remove_plugin("verify")