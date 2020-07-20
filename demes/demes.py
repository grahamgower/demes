from typing import List, Dict, Union, Callable, Any, Tuple, Optional
import itertools
import math
import collections

import attr

Number = Union[int, float]
ID = str
Time = Number
Size = Number
Rate = float
Proportion = float


# Validator functions.


def positive(self: Any, attribute: attr.Attribute, value: Number) -> None:
    if value <= 0:
        raise ValueError(f"{attribute.name} must be greater than zero")


def non_negative(self: Any, attribute: attr.Attribute, value: Number) -> None:
    if value < 0:
        raise ValueError(f"{attribute.name} must be non-negative")


def finite(self: Any, attribute: attr.Attribute, value: Number) -> None:
    if math.isinf(value):
        raise ValueError(f"{attribute.name} must be finite")


def unit_interval(self: Any, attribute: attr.Attribute, value: Number) -> None:
    if not (0 <= value <= 1):
        raise ValueError(f"must have 0 <= {attribute.name} <= 1")


ValidatorFunc = Callable[[Any, attr.Attribute, Number], None]


def optional(func: Union[ValidatorFunc, List[ValidatorFunc]]) -> ValidatorFunc:
    """
    Wraps one or more validator functions with an "if not None" clause.
    """
    if isinstance(func, (tuple, list)):
        func_list = func
    else:
        func_list = [func]

    def validator(self: Any, attribute: attr.Attribute, value: Any) -> None:
        if value is not None:
            for func in func_list:
                func(self, attribute, value)

    return validator


@attr.s(auto_attribs=True)
class Epoch:
    """
    Population size parameters for a deme in a specified time period.
    Times follow the backwards-in-time convention (time values increase
    from the present towards the past).

    :ivar start_time: The start time of the epoch.
    :ivar end_time: The end time of the epoc.
    :ivar initial_size: Population size at ``start_time``.
    :ivar final_size: Population size at ``end_time``.
        If ``initial_size != final_size``, the population size changes
        monotonically between the start and end times.
        TODO: traditionally, this is an exponential increase or decrease,
              due to tractibility under the coalescent. But other functions
              may be reasonable choices, particularly for non-coalescent
              simulators.
    """

    start_time: Time = attr.ib(validator=[non_negative, finite])
    end_time: Time = attr.ib(default=None, validator=optional(non_negative))
    initial_size: Size = attr.ib(default=None, validator=optional([positive, finite]))
    final_size: Size = attr.ib(default=None, validator=optional([positive, finite]))

    def __attrs_post_init__(self) -> None:
        if self.initial_size is None and self.final_size is None:
            raise ValueError("must set either initial_size or final_size")
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time >= self.end_time
        ):
            raise ValueError("must have start_time < end_time")
        if self.final_size is None:
            self.final_size = self.initial_size

    @property
    def dt(self) -> Number:
        """
        The time span of the epoch.
        """
        return self.end_time - self.start_time


@attr.s(auto_attribs=True)
class Migration:
    """
    Parameters for continuous migration from one deme to another.
    Source and destination demes follow the backwards-in-time coalescent
    convention.

    :ivar source: The source deme.
    :ivar dest: The destination deme.
    :ivar time: The time at which the migration rate becomes activate.
    :ivar rate: The rate of migration. Set to zero to disable migrations after
        the given time.
    """

    source: ID = attr.ib()
    dest: ID = attr.ib()
    time: Time = attr.ib(validator=[non_negative, finite])
    rate: Rate = attr.ib(validator=[non_negative, finite])

    def __attrs_post_init__(self) -> None:
        if self.source == self.dest:
            raise ValueError("source and dest cannot be the same deme")


@attr.s(auto_attribs=True)
class Pulse:
    """
    Parameters for a pulse of migration from one deme to another.
    Source and destination demes follow the backwards-in-time coalescent
    convention.

    :ivar source: The source deme.
    :ivar dest: The destination deme.
    :ivar time: The time of migration.
    :ivar proportion: At the instant after migration, this is the proportion
        of individuals in the destination deme made up of individuals from
        the source deme.
    """

    source: ID = attr.ib()
    dest: ID = attr.ib()
    time: Time = attr.ib(validator=[non_negative, finite])
    proportion: Proportion = attr.ib(validator=unit_interval)

    def __attrs_post_init__(self) -> None:
        if self.source == self.dest:
            raise ValueError("source and dest cannot be the same deme")


@attr.s(auto_attribs=True)
class Deme:
    """
    A collection of individuals that are exchangeable at any fixed time.

    :ivar id: A string identifier for the deme.
    :ivar ancestor: The string identifier of the ancestor of this deme.
        If the deme has no ancestor, this should be ``None``.
    :ivar epochs: A list of epochs, which define the population size(s) of
        the deme. The deme must be created with exactly one epoch.
        Additional epochs may be added with :meth:`.add_epoch`
    :vartype epochs: list of :class:`.Epoch`
    """

    id: ID = attr.ib()
    ancestor: Optional[ID] = attr.ib()
    epochs: List[Epoch] = attr.ib()

    @epochs.validator
    def _check_epochs(self, attribute: attr.Attribute, value: List[Epoch]) -> None:
        if len(self.epochs) != 1:
            raise ValueError(
                "Deme must be created with exactly one epoch."
                "Use add_epoch() to supply additional epochs."
            )

    def __attrs_post_init__(self) -> None:
        if self.id == self.ancestor:
            raise ValueError(f"{self.id} cannot be its own ancestor")

    def add_epoch(self, epoch: Epoch) -> None:
        """
        Add an epoch to the deme's epoch list.
        Epochs must be non overlapping and added in time-increasing order.

        :param .Epoch epoch: The epoch to add.
        """
        assert len(self.epochs) > 0
        prev_epoch = self.epochs[len(self.epochs) - 1]
        if epoch.start_time < prev_epoch.start_time:
            raise ValueError(
                "epochs must be non overlapping and added in time-increasing order"
            )
        if epoch.end_time is None:
            epoch.end_time = prev_epoch.end_time
        prev_epoch.end_time = epoch.start_time
        if epoch.initial_size is None:
            epoch.initial_size = prev_epoch.final_size
        if epoch.final_size is None:
            epoch.final_size = epoch.initial_size
        self.epochs.append(epoch)

    @property
    def start_time(self) -> Number:
        """
        The start time of the deme's existence.
        """
        return self.epochs[0].start_time

    @property
    def end_time(self) -> Number:
        """
        The end time of the deme's existence.
        """
        return self.epochs[-1].end_time

    @property
    def dt(self) -> Number:
        """
        The time span over which the deme exists.
        """
        return self.end_time - self.start_time


@attr.s(auto_attribs=True)
class DemeGraph:
    """
    A directed graph that describes a demography. Vertices are demes and edges
    correspond to ancestor/descendent relations. Edges are directed from
    descendents to ancestors.

    :ivar description: A human readable description of the demography.
    :ivar time_units: The units of time used for the demography. This is
        commonly ``years`` or ``generations``, but can be any string.
    :ivar generation_time: The generation time of demes.
        TODO: The units of generation_time are undefined if
        ``time_units="generations"``, so we likely need an additional
        ``generation_time_units`` attribute.
    :ivar default_Ne: The default population size to use when creating new
        demes with :meth:`.deme`. May be ``None``.
    :ivar doi: If the deme graph describes a published demography, the DOI
        should be be given here. May be ``None``.
    :ivar demes: A list of demes in the demography.
        Not intended to be passed when the deme graph is instantiated.
        Use :meth:`.deme` instead.
    :vartype demes: list of :class:`.Deme`
    :ivar migrations: A list of continuous migrations for the demography.
        Not intended to be passed when the deme graph is instantiated.
        Use :meth:`migration` or :meth:`symmetric_migration` instead.
    :vartype migrations: list of :class:`.Migration`
    :ivar pulses: A list of migration pulses for the demography.
        Not intended to be passed when the deme graph is instantiated.
        Use :meth:`pulse` instead.
    """

    description: str = attr.ib()
    time_units: str = attr.ib()
    generation_time: Time = attr.ib(validator=[positive, finite])
    default_Ne: Size = attr.ib(default=None, validator=optional([positive, finite]))
    doi: str = attr.ib(default=None)
    demes: List[Deme] = attr.ib(factory=list)
    migrations: List[Migration] = attr.ib(factory=list)
    pulses: List[Pulse] = attr.ib(factory=list)

    def __attrs_post_init__(self) -> None:
        self._deme_map: Dict[ID, Deme] = dict()

    def __getitem__(self, deme_id: ID) -> Deme:
        """
        Return the :class:`.Deme` with the specified id.
        """
        return self._deme_map[deme_id]

    def __contains__(self, deme_id: ID) -> bool:
        """
        Check if the deme graph contains a deme with the specified id.
        """
        return deme_id in self._deme_map

    def deme(
        self,
        id: ID,
        ancestor: Optional[ID] = None,
        start_time: Number = 0,
        end_time: Number = float("inf"),
        initial_size: Optional[Number] = None,
        final_size: Optional[Number] = None,
        epochs: Optional[List[Epoch]] = None,
    ) -> None:
        """
        Add a deme to the graph.

        :param str id: A string identifier for the deme.
        :param str ancestor: The string identifier of the ancestor of this deme.
            May be ``None``.
        :param start_time: The time at which this deme begins existing.
        :param end_time: The time at which this deme stops existing.
            If the deme has an ancestor the ``end_time`` will be set to the
            ancestor's ``start_time``.
        :param initial_size: The initial population size of the deme. If ``None``,
            this is taken from the deme graph's ``default_Ne`` field.
        :param final_size: The final population size of the deme. If ``None``,
            the deme has a constant ``initial_size`` population size.
        :param epochs: Additional epochs that define population size changes for
            the deme.
        """
        if initial_size is None:
            initial_size = self.default_Ne
            if initial_size is None:
                raise ValueError(f"must set initial_size for {id}")
        if final_size is None:
            final_size = initial_size
        if ancestor is not None:
            if ancestor not in self:
                raise ValueError(f"{ancestor} not in deme graph")
            end_time = self[ancestor].epochs[0].start_time
        epoch = Epoch(
            start_time, end_time, initial_size=initial_size, final_size=final_size
        )
        deme = Deme(id, ancestor, [epoch])
        if epochs is not None:
            for epoch in epochs:
                deme.add_epoch(epoch)
        self._deme_map[deme.id] = deme
        self.demes.append(deme)

    def check_time_intersection(
        self, deme_id1: ID, deme_id2: ID, time: Optional[Number], closed: bool = False
    ) -> Tuple[Number, Number]:
        deme1 = self[deme_id1]
        deme2 = self[deme_id2]
        time_lo = max(deme1.start_time, deme2.start_time)
        time_hi = min(deme1.end_time, deme2.end_time)
        if time is not None:
            if (not closed and not (time_lo <= time < time_hi)) or (
                closed and not (time_lo <= time <= time_hi)
            ):
                bracket = "]" if closed else ")"
                raise ValueError(
                    f"{time} not in interval [{time_lo}, {time_hi}{bracket}, "
                    f"as defined by the time-intersection of {deme1} and {deme2}."
                )
        return time_lo, time_hi

    def symmetric_migration(
        self,
        *demes: ID,
        rate: Number = 0,
        start_time: Optional[Number] = None,
        end_time: Optional[Number] = None,
    ) -> None:
        """
        Add continuous symmetric migrations between all pairs of demes in a list.

        :param demes: list of deme IDs. Migration is symmetric between all
            pairs of demes in this list.
        :param rate: The rate of migration per ``time_units``.
        :param start_time: The time at which the migration rate is enabled.
        :param end_time: The time at which the migration rate is disabled.
        """
        if len(demes) < 2:
            raise ValueError("must specify two or more demes")
        for source, dest in itertools.permutations(demes, 2):
            self.migration(source, dest, rate, start_time, end_time)

    def migration(
        self,
        source: ID,
        dest: ID,
        rate: Number = 0,
        start_time: Optional[Number] = None,
        end_time: Optional[Number] = None,
    ) -> None:
        """
        Add continuous migration from one deme to another.
        Source and destination demes follow the backwards-in-time coalescent
        convention.

        :param source: The source deme.
        :param dest: The destination deme.
        :param rate: The rate of migration per ``time_units``.
        :param start_time: The time at which the migration rate is enabled.
            If ``None``, the start time is defined by the earliest time at
            which the demes coexist.
        :param end_time: The time at which the migration rate is disabled.
            If ``None``, the end time is defined by the latest time at which
            the demes coexist.
        """
        for deme_id in (source, dest):
            if deme_id not in self:
                raise ValueError(f"{deme_id} not in deme graph")
        time_lo, time_hi = self.check_time_intersection(source, dest, start_time)
        if start_time is None:
            start_time = time_lo
        self.migrations.append(Migration(source, dest, start_time, rate))
        if end_time is not None:
            self.check_time_intersection(source, dest, end_time)
            self.migrations.append(Migration(source, dest, end_time, 0))

    def pulse(self, source: ID, dest: ID, proportion: Number, time: Number) -> None:
        """
        Add a pulse of migration at a fixed time.
        Source and destination demes follow the backwards-in-time coalescent
        convention.

        :param source: The source deme.
        :param dest: The destination deme.
        :param proportion: At the instant after migration, this is the proportion
            of individuals in the destination deme made up of individuals from
            the source deme.
        :param time: The time at which migrations occur.
        """
        for deme_id in (source, dest):
            if deme_id not in self:
                raise ValueError(f"{deme_id} not in deme graph")
        if self[source].ancestor == dest or self[dest].ancestor == source:
            raise ValueError(f"{source} and {dest} have ancestor/descendent relation")
        self.check_time_intersection(source, dest, time, closed=True)
        self.pulses.append(Pulse(source, dest, time, proportion))

    def subgraph(
        self,
        deme_id: ID,
        ancestors: List[ID],
        proportions: List[Rate],
        start_time: Number = 0,
        end_time: Optional[Number] = None,
        initial_size: Optional[Number] = None,
        final_size: Optional[Number] = None,
        epochs: Optional[List[Epoch]] = None,
    ) -> None:
        """
        Add a new deme to the graph. The new deme may have multiple ``ancestors``,
        which connect the new deme to the graph via pulse migrations with the
        supplied ``proportions``.

        GG: I'm not sure this is really a subgraph, but I couldn't think of a
        more appropriate name.
        TODO: The semantics when ``end_time=None`` are likely broken!

        :param deme_id: A string identifier for the deme at the root of the subgraph.
        :param ancestors: The ancestor(s) of the subgraph's root deme.
        :paramtype ancestors: list of str
        :param proportions: The ancestry proportion for each ancestor.
        :paramtype proportions: list of float
        :param start_time: See :meth:`.deme`.
        :param end_time: See :meth:`.deme`.
        :param initial_size: See :meth:`.deme`.
        :param final_size: See :meth:`.deme`.
        :param epochs: See :meth:`.deme`.
        """
        if len(ancestors) != len(proportions):
            raise ValueError("len(ancestors) != len(proportions)")
        if not math.isclose(sum(proportions), 1.0):
            raise ValueError("proportions must sum to 1")
        if end_time is None:
            end_time = max(self[anc].start_time for anc in ancestors)
        self.deme(
            deme_id,
            start_time=start_time,
            end_time=end_time,
            initial_size=initial_size,
            final_size=final_size,
            epochs=epochs,
        )
        for j, ancestor in enumerate(ancestors):
            p = proportions[j] / sum(proportions[j:])
            self.pulse(source=deme_id, dest=ancestor, proportion=p, time=end_time)
        assert p == 1

    def asdict(self) -> Dict[str, Any]:
        """
        Return a dict representation of the deme graph.
        """
        return attr.asdict(self)

    def asdict_compact(self) -> Dict[str, Any]:
        """
        Return a dict representation of the deme graph, with default and
        implicit values removed.
        """
        d: Dict[str, Any] = dict(
            description=self.description,
            time_units=self.time_units,
            generation_time=self.generation_time,
        )
        if self.doi is not None:
            d.update(doi=self.doi)
        if self.default_Ne is not None:
            d.update(default_Ne=self.default_Ne)

        assert len(self.demes) > 0
        d.update(demes=dict())
        for deme in self.demes:
            deme_dict: Dict[str, Any] = dict()
            if deme.ancestor is not None:
                deme_dict.update(ancestor=deme.ancestor)
            assert len(deme.epochs) > 0
            if deme.epochs[0].start_time > 0:
                deme_dict.update(start_time=deme.epochs[0].start_time)
            deme_dict.update(initial_size=deme.epochs[0].initial_size)
            if deme.epochs[0].final_size != deme.epochs[0].initial_size:
                deme_dict.update(final_size=deme.epochs[0].final_size)

            e_list = []
            for j, epoch in enumerate(deme.epochs):
                e: Dict[str, Any] = dict()
                if epoch.start_time > 0:
                    e.update(start_time=epoch.start_time)
                if epoch.initial_size == epoch.final_size:
                    e.update(initial_size=epoch.initial_size)
                else:
                    e.update(final_size=epoch.final_size)
                    if (
                        j == 0
                        or j == len(deme.epochs) - 1
                        or epoch.initial_size != deme.epochs[j - 1].final_size
                    ):
                        e.update(initial_size=epoch.initial_size)
                e_list.append(e)
            if len(e_list) > 1:
                deme_dict.update(epochs=e_list[1:])
            d["demes"][deme.id] = deme_dict

        if len(self.migrations) > 0:
            m_dict = collections.defaultdict(list)
            for migration in self.migrations:
                m_dict[(migration.source, migration.dest)].append(migration)

            m_list = []
            for (source, dest), m_sublist in m_dict.items():
                time_lo, time_hi = self.check_time_intersection(source, dest, None)
                while True:
                    migration, m_sublist = m_sublist[0], m_sublist[1:]
                    m_list.append(dict(source=source, dest=dest, rate=migration.rate))
                    if migration.time != time_lo:
                        m_list[-1].update(start_time=migration.time)
                    if len(m_sublist) == 0:
                        break
                    if migration.rate != 0 and m_sublist[0].rate == 0:
                        if m_sublist[0].time != time_hi:
                            m_list[-1].update(end_time=m_sublist[0].time)
                        m_sublist = m_sublist[1:]
                        if len(m_sublist) == 0:
                            break
            # TODO collapse into symmetric migrations
            d.update(migrations=m_list)

        if len(self.pulses) > 0:
            d.update(pulses=[attr.asdict(pulse) for pulse in self.pulses])

        return d
