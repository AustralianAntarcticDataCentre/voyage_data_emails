"""
Populate voyage data tables from CSV emails.
"""

from datetime import datetime
import email
import logging
import os
import re

from csv_email import CSVEmailParser
from settings import (
	CSV_FOLDER, get_csv_file_types, get_database_client, get_email_client,
	LOGGING_FORMAT, LOGGING_LEVEL
)


logger = logging.getLogger(__name__)


class VoyageEmailParser(CSVEmailParser):

	def __init__(self, database, settings, table_name, subject_values):
		"""
		Create a new voyage CSV email parser.

		Each of the parameters passed into this method are stored in the object.


		Parameters
		----------

		database : object
			Helper class for accessing the database used to store CSV data.

		settings : dict
			Dictionary used to extract data from the CSV email.
			The details are specific to the matched email format.

		table_name : str
			Name of the table in the database to update with CSV rows.

		subject_values : dict
			Values that were extracted from the email subject.
		"""

		self.database = database

		self.table_name = table_name


		# Settings to save a copy of the CSV.
		try:
			save_csv = settings['save_csv']

			file_name_format = save_csv['file_name_format'].strip()

			# Create the file name from the subject parts.
			file_name = file_name_format.format(**subject_values)

			self.save_file_path = os.path.join(CSV_FOLDER, file_name)

		except KeyError:
			self.save_file_path = None


		# Save details about the expected columns in the CSV.
		self.csv_columns = []

		# Loop each of the CSV column settings.
		for csv_name, details in settings['load_csv']['columns'].items():
			# Use the CSV column name if a database field name is not given.
			field_name = details.get('field', csv_name)

			self.csv_columns.append([csv_name, field_name, details])

	def process_csv_content(self, content):
		"""
		Save the CSV to a file and continue processing it.


		Parameters
		----------

		content : str
			Text from the email, processed from the raw format.
		"""

		if self.save_file_path is not None:
			# Write the contents of the CSV to the file.
			with open(self.save_file_path, 'w') as f:
				f.write(content)

		# Continue processing the message.
		CSVEmailParser.process_csv_content(self, content)

	def process_csv_row(self, csv_row):
		"""
		Process a single row of CSV from a voyage email.


		Parameters
		----------

		row : dict
			Column names and their values.
		"""

		#print(sorted(csv_row.keys()))

		# Stores the field names and values to be inserted into the database.
		fields = {}

		# Loop each of the CSV column details.
		for csv_name, field_name, details in self.csv_columns:
			# Get the value and type from the row or skip to the next column.
			try:
				value = csv_row[csv_name]
				item_type = details['type']
			except KeyError:
				continue

			if 'datetime' == item_type:
				# datetime requires the format text for conversion.
				try:
					csv_format = details['csv_format'].strip()
				except KeyError:
					continue

				# Convert the CSV text value into a datetime value.
				value = datetime.strptime(value, csv_format)

			fields[field_name] = value

		self.database.insert_row(self.table_name, fields)


def process_message(database, message, csv_file_types):
	"""
	Process a message containing CSV voyage data.


	Parameters
	----------

	database : object
		Helper class for accessing the database used to store CSV data.

	message : email.message.Message
		Message (hopefully) with CSV content to be processed.

	csv_file_types : list
		List of dictionaries containing checks and settings for the different
		types of CSV emails that can be processed.


	Raises
	------

	KeyError
		If any of the required settings are not in the CSV types dictionary.


	Returns
	-------

	bool
		True if the message was processed, False if no handler could be found.
	"""

	# parseaddr() splits "From" into name and address.
	# https://docs.python.org/3/library/email.util.html#email.utils.parseaddr
	email_from = email.utils.parseaddr(message['From'])[1]

	logger.debug('Email is from "%s".', email_from)

	subject = message['Subject']

	logger.debug('Email subject is "%s".', subject)

	for csv_type in csv_file_types:
		check = csv_type['check']

		required_from = check['from']

		# Skip this message if it did not come from the correct sender.
		if email_from != required_from:
			msg = 'Email is not from the correct sender (%s != %s).'
			logger.warning(msg, email_from, required_from)
			continue

		# Use the compiled RegEx if it is available.
		if 'subject_regex_compiled' in check:
			subject_regex = check['subject_regex_compiled']

		# Compile and save the RegEx otherwise.
		else:
			subject_regex_list = check['subject_regex']
			subject_regex = re.compile(''.join(subject_regex_list))
			check['subject_regex_compiled'] = subject_regex

		# Check if the message subject matches the RegEx.
		match_data = subject_regex.match(subject)

		# Skip this message if the subject does not match the RegEx.
		if match_data is None:
			logger.warning('Email subject does not match the required format.')
			continue

		# Get a dict of the values matched in the regex.
		match_dict = match_data.groupdict()

		logger.debug('Extracted %s from subject.', match_dict)

		save_table = csv_type['save_table']

		# Get the table name template.
		table_name_format = save_table['file_name_format'].strip()

		# Create the table name from the regex values.
		table_name = table_name_format.format(**match_dict)

		# Create the required table if it does not exist.
		if not database.table_exists(table_name):
			logger.info('Table "%s" does not exist.', table_name)

			columns = csv_type['load_csv']['columns']

			database.create_table(table_name, columns)

		else:
			logger.debug('Table "%s" exists.', table_name)

		parser = VoyageEmailParser(database, csv_type, table_name, match_dict)
		parser.process_message(message)

		# No need to check other CSV parsers once one is complete.
		return True

	# Returns False if none of the parsers matched the given email.
	return False


def process_emails():
	"""
	Main function to import CSV emails into the database.

	Creates a database and email connection then loops all the emails in the
	inbox.


	Returns
	-------

	bool
		False if settings cannot be loaded.
	"""

	csv_file_types = get_csv_file_types()

	if csv_file_types is None:
		logger.error('CSV file types could not be read from `settings.yaml`.')
		return False

	with get_database_client() as database, get_email_client() as email_client:
		email_client.select_inbox()

		for message in email_client.loop_email_messages():
			process_message(database, message, csv_file_types)

	return True


if '__main__' == __name__:
	logging.basicConfig(format=LOGGING_FORMAT, level=LOGGING_LEVEL)

	logger.info('Started reading emails.')

	process_emails()

	logger.info('Finished reading emails.')
