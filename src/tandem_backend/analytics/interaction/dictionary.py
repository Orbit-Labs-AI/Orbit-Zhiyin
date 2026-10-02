"""interaction field definitions, owned by this feature family."""

FEATURES = {'interaction.message_intents': {'name': 'interaction.message_intents',
                                 'unit': 'label',
                                 'rule': 'Consume visible reviewed annotations, never promote lexical '
                                         'candidates',
                                 'source': 'attrs.interaction',
                                 'denominator': None,
                                 'type': 'annotated_observation',
                                 'missing_semantics': 'null if unsupported; '
                                                      'coverage/effective_samples/unknown_counts describe '
                                                      'known subsets',
                                 'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                               'artifact_revision, available_at',
                                 'path_prefix': 'bottleneck_features'},
 'interaction.friction_types': {'name': 'interaction.friction_types',
                                'unit': 'label',
                                'rule': 'Consume visible reviewed annotations, never promote lexical '
                                        'candidates',
                                'source': 'attrs.interaction',
                                'denominator': None,
                                'type': 'annotated_observation',
                                'missing_semantics': 'null if unsupported; '
                                                     'coverage/effective_samples/unknown_counts describe '
                                                     'known subsets',
                                'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                              'artifact_revision, available_at',
                                'path_prefix': 'bottleneck_features'},
 'interaction.confirmed_correction_count': {'name': 'interaction.confirmed_correction_count',
                                            'unit': 'human message',
                                            'rule': 'Distinct reviewed correction messages with prior '
                                                    'same-task target',
                                            'source': 'attrs.interaction + target event',
                                            'denominator': None,
                                            'type': 'deterministic_derived',
                                            'missing_semantics': 'null if unsupported; '
                                                                 'coverage/effective_samples/unknown_counts '
                                                                 'describe known subsets',
                                            'provenance': 'event_uid, call_uid, validation_uid, '
                                                          'criterion_uid, artifact_revision, available_at',
                                            'path_prefix': 'bottleneck_features'},
 'interaction.confirmed_correction_rate': {'name': 'interaction.confirmed_correction_rate',
                                           'unit': 'ratio',
                                           'rule': 'Confirmed correction messages / human messages with '
                                                   'reviewed determinable intents',
                                           'source': 'attrs.interaction',
                                           'denominator': 'confirmed human messages with reviewed intents',
                                           'type': 'deterministic_derived',
                                           'missing_semantics': 'null if unsupported; '
                                                                'coverage/effective_samples/unknown_counts '
                                                                'describe known subsets',
                                           'provenance': 'event_uid, call_uid, validation_uid, '
                                                         'criterion_uid, artifact_revision, available_at',
                                           'path_prefix': 'bottleneck_features'},
 'interaction.repeated_requirement_count': {'name': 'interaction.repeated_requirement_count',
                                            'unit': 'human message',
                                            'rule': 'Subsequent emphasis of the same task/object/requirement '
                                                    'IDs',
                                            'source': 'attrs.interaction.requirements',
                                            'denominator': None,
                                            'type': 'deterministic_derived',
                                            'missing_semantics': 'null if unsupported; '
                                                                 'coverage/effective_samples/unknown_counts '
                                                                 'describe known subsets',
                                            'provenance': 'event_uid, call_uid, validation_uid, '
                                                          'criterion_uid, artifact_revision, available_at',
                                            'path_prefix': 'bottleneck_features'},
 'interaction.intervention_points': {'name': 'interaction.intervention_points',
                                     'unit': 'event relation',
                                     'rule': 'Previous/next execution step in record order and explicit task',
                                     'source': 'event.seq + task_uid',
                                     'denominator': None,
                                     'type': 'deterministic_derived',
                                     'missing_semantics': 'null if unsupported; '
                                                          'coverage/effective_samples/unknown_counts '
                                                          'describe known subsets',
                                     'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                                   'artifact_revision, available_at',
                                     'path_prefix': 'bottleneck_features'}}
