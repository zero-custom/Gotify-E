import logging
import re


class TokenSanitizingFilter(logging.Filter):

    TOKEN_PATTERN = re.compile(r"token=[^&\s]+")

    def filter(self, record: logging.Record) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.TOKEN_PATTERN.sub("token=[masked]", record.msg)
        if record.args:
            record.args = tuple(
                self.TOKEN_PATTERN.sub("token=[masked]", str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True
