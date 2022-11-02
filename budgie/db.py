from sqlalchemy import (
    create_engine,
    String,
    Column,
    Integer,
    Date,
    Numeric,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func

from .schemas import AccountSchema, EntrySchema, UserSchema

base = declarative_base()


class UserModel(base):
    __tablename__ = "app_user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True)
    password = Column(String)
    salt = Column(String)
    name = Column(String)
    created = Column(Date)


class AccountModel(base):
    __tablename__ = "account"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"))
    name = Column(String)
    description = Column(String)
    type = Column(String)
    credit_entries = relationship(
        "EntryModel", primaryjoin="EntryModel.credit_account_id == AccountModel.id"
    )
    debit_entries = relationship(
        "EntryModel", primaryjoin="EntryModel.debit_account_id == AccountModel.id"
    )
    __table_args__ = (UniqueConstraint("name", "user_id"),)


class EntryTagModel(base):
    """Association table for entry tags"""

    __tablename__ = "entry_tag"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"))
    entry_id = Column(Integer, ForeignKey("entry.id"))
    tag_id = Column(Integer, ForeignKey("tag.id"))
    entry = relationship("EntryModel", back_populates="tags")
    tag = relationship("TagModel", back_populates="entries")


class TagModel(base):
    __tablename__ = "tag"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"))
    tag = Column(String)
    entries = relationship("EntryTagModel", back_populates="tag")


class EntryModel(base):
    __tablename__ = "entry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"))
    who = Column(String)
    when = Column(Date)
    credit_account_id = Column(Integer, ForeignKey(AccountModel.id))
    credit_account = relationship(
        "AccountModel",
        back_populates="credit_entries",
        foreign_keys=[credit_account_id],
    )
    debit_account_id = Column(Integer, ForeignKey(AccountModel.id))
    debit_account = relationship(
        "AccountModel", back_populates="debit_entries", foreign_keys=[debit_account_id]
    )
    amount = Column(Numeric)
    description = Column(String)
    tags = relationship("EntryTagModel", back_populates="entry")


class Database:
    def __init__(self, db_string):
        self.db = create_engine(db_string, echo=True)
        base.metadata.create_all(self.db)
        self.current_uid = None

    def set_current_user(self, email: str):
        with sessionmaker(self.db).begin() as session:
            user = session.query(UserModel).filter_by(email=email).first()
            self.current_uid = user.id

    def create_account(self, account):
        with sessionmaker(self.db).begin() as session:
            acc = AccountModel(
                user_id=self.current_uid,
                name=account["name"],
                description=account["description"],
                type=account["type"],
            )
            session.add(acc)
            session.commit()

    def create_tag(self, tag: str):
        with sessionmaker(self.db).begin() as session:
            tag = TagModel(
                user_id=self.current_uid,
                tag=tag,
            )
            session.add(tag)
            session.commit()

    def create_user(self, user):
        with sessionmaker(self.db).begin() as session:
            user_m = UserModel(
                name=user["name"],
                email=user["email"],
                password=user["password"],
                salt=user["salt"],
                created=user["created"],
            )
            session.add(user_m)
            session.commit()

    def get_user(self, email):
        with sessionmaker(self.db).begin() as session:
            user = session.query(UserModel).filter_by(email=email).first()

            if not user:
                return None

            return UserSchema().load(
                {
                    "name": user.name,
                    "email": user.email,
                    "password": user.password,
                    "salt": user.salt,
                    "created": user.created.isoformat(),
                }
            )

    def add_entry(self, entry):
        with sessionmaker(self.db).begin() as session:
            entry_m = EntryModel(
                user_id=self.current_uid,
                who=entry["who"],
                when=entry["when"],
                amount=entry["amount"],
                description=entry["description"],
            )
            debit_account = (
                session.query(AccountModel)
                .filter_by(name=entry["debit_account"])
                .first()
            )
            credit_account = (
                session.query(AccountModel)
                .filter_by(name=entry["credit_account"])
                .first()
            )
            entry_m.credit_account = credit_account
            entry_m.debit_account = debit_account

            if entry.get("tags", None):
                for tag_name in entry["tags"]:
                    entry_tag = EntryTagModel(user_id=self.current_uid)
                    entry_tag.tag = (
                        session.query(TagModel).filter(TagModel.tag == tag_name).first()
                    )
                    if not entry_tag.tag:
                        entry_tag.tag = TagModel(user_id=self.current_uid, tag=tag_name)

                    entry_m.tags.append(entry_tag)

            session.add(entry_m)

    def delete_entry(self, entry_id):
        with sessionmaker(self.db).begin() as session:
            entry = (
                session.query(EntryModel)
                .filter_by(user_id=self.current_uid, id=entry_id)
                .first()
            )
            if not entry:
                return False

            # TODO: this could be improved with cascade
            for entry_tag in entry.tags:
                session.delete(entry_tag)
            session.delete(entry)
            return True

    def list_entries(self, **kwargs):
        """
        List entries from database
        To filter the entries use following keywork arguments
            - debit_account=<name> - show entries debiting this account
            - credit_account=<name> - show entries crediting this account
        """
        dr = kwargs.get("debit_account", None)
        cr = kwargs.get("credit_account", None)

        with sessionmaker(self.db).begin() as session:
            entries = session.query(EntryModel).filter_by(user_id=self.current_uid)
            if dr:
                entries = entries.filter(EntryModel.debit_account.has(name=dr))
            if cr:
                entries = entries.filter(EntryModel.credit_account.has(name=cr))

            entry_list = []
            for entry in entries:
                entry_list.append(
                    EntrySchema().load(
                        {
                            "id": entry.id,
                            "when": str(entry.when),
                            "description": entry.description,
                            "credit_account": entry.credit_account.name,
                            "debit_account": entry.debit_account.name,
                            "amount": entry.amount,
                            "who": entry.who,
                            # entry.tags are EntryTag associations
                            # Maybe association_proxy could be used?
                            "tags": [entry_tag.tag.tag for entry_tag in entry.tags],
                        }
                    )
                )
            return entry_list

    def list_accounts(self, **kwargs):
        """
        List accounts from database
        To filter the accounts use following keyword arguments
            - type [string] - show accounts of that type
        """
        type_ = kwargs.get("type", None)
        filter_by = {}
        if type_:
            filter_by["type"] = type_

        with sessionmaker(self.db).begin() as session:
            accounts = session.query(AccountModel).filter_by(
                user_id=self.current_uid, **filter_by
            )

            acc_list = []
            for account in accounts:
                acc_list.append(
                    AccountSchema().load(
                        {
                            "name": account.name,
                            "description": account.description,
                            "type": account.type,
                        }
                    )
                )
            return acc_list

    def get_account_balance(self, account):
        with sessionmaker(self.db).begin() as session:
            sum_cr = (
                session.query(func.sum(EntryModel.amount))
                .filter_by(user_id=self.current_uid)
                .filter(EntryModel.credit_account.has(name=account))
                .scalar()
            )
            sum_dr = (
                session.query(func.sum(EntryModel.amount))
                .filter_by(user_id=self.current_uid)
                .filter(EntryModel.debit_account.has(name=account))
                .scalar()
            )
            sum_dr = 0 if not sum_dr else sum_dr
            sum_cr = 0 if not sum_cr else sum_cr

            return sum_dr - sum_cr
