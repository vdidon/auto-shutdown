# Fiabilité au retour de veille

Ce document explique le défaut que ce programme a été conçu pour éviter, les
règles qui l'en protègent, et les causes de réveil intempestif qui relèvent de
la configuration de la machine plutôt que du logiciel.

## Le problème

Sur une machine en veille moderne, l'enchaînement suivant s'observe dans le
journal Windows :

| Heure | Événement | Interprétation |
|---|---|---|
| 08:14:49 | Power-Troubleshooter | la machine sort de veille |
| 08:14:51 | Kernel-Power **187** | un processus appelle `SetSuspendState` |
| 08:14:56 | Kernel-Power **42** | la machine se rendort |
| 08:15:02 | Kernel-Power **107** | elle se réveille à nouveau |

Deux secondes après le réveil, l'utilitaire de programmation relance son action.
L'utilisateur voit son poste s'allumer, afficher brièvement l'écran de
démarrage, puis repartir en veille — parfois plusieurs fois de suite.

La cause est presque toujours la même : l'échéance est enregistrée comme une
**heure absolue**, et la tâche n'est pas désarmée. Au réveil, cette heure est
dépassée, la condition est donc vraie, et l'action repart aussitôt.

## Comment ce programme s'en garde

Quatre règles, toutes vérifiées par la suite de tests :

1. **Base de temps monotone.** L'échéance est un instant `time.monotonic()`, pas
   une date. Un changement d'heure système, un fuseau ou un décalage NTP ne
   peuvent pas la rendre subitement « dépassée ».
2. **Désarmement avant exécution.** La tâche quitte l'état armé *avant* que
   l'action ne parte. Il n'existe aucun instant où une tâche déjà déclenchée
   reste armée.
3. **Annulation à la reprise.** Le programme s'abonne à `WM_POWERBROADCAST` via
   `RegisterSuspendResumeNotification`. Toute reprise annule une tâche encore
   armée et le signale par une notification. Après un réveil, seul l'utilisateur
   peut réarmer.
4. **Détection d'interruption du décompte.** Si deux passages du décompte sont
   séparés par plus d'une minute, c'est que le processus a été gelé — machine
   suspendue. L'échéance franchie pendant ce trou est annulée au lieu d'être
   jouée. Cette règle ne dépend d'aucune notification Windows : elle protège
   même si l'abonnement échoue.

S'y ajoute une précaution à l'exécution : avant toute suspension, le programme
attend quelques secondes sans activité clavier ni souris. Sur une machine où la
souris est armée pour le réveil, appeler `SetSuspendState` alors qu'un mouvement
est encore en cours de traitement fait ressortir le système de veille dans la
seconde.

Les tests de l'ordonnanceur rejouent les enchaînements du tableau ci-dessus avec
une horloge simulée, sans jamais endormir la machine.

## Ce que le programme ne peut pas corriger

Deux causes de réveil intempestif relèvent de la configuration de la machine, et
aucun logiciel ne les corrigera à sa place.

### La veille moderne (`S0 Low Power Idle`)

```console
> powercfg /a
Les états de veille suivants sont disponibles sur ce système :
    Veille (Mode faible consommation S0) Connecté au réseau
    Mettre en veille prolongée
```

Si `S3` est absent de cette liste, la « veille » ne suspend pas la machine :
elle reste alimentée, le réseau reste connecté, et le système remonte
régulièrement de son état de repos. Ventilateurs qui repartent et voyants
allumés sont le fonctionnement normal de ce mode, pas une anomalie.

**Remède** : préférer `Mettre en veille prolongée` (S4), qui coupe réellement
l'alimentation. C'est l'action par défaut du programme. On peut aussi demander à
Windows de basculer de lui-même en veille prolongée après un temps de veille
moderne :

```console
> powercfg /change hibernate-timeout-ac 30
```

### Les périphériques armés pour le réveil

```console
> powercfg /devicequery wake_armed
Souris HID (004)
```

Une souris armée réveille la machine au moindre mouvement — un choc sur le
bureau, une dérive du capteur optique, un animal domestique. Pour la désarmer :

```console
> powercfg /devicedisablewake "Souris HID (004)"
```

Le clavier reste alors le seul moyen de réveiller le poste. Deux autres
commandes utiles pour un diagnostic :

```console
> powercfg /lastwake      # ce qui a réveillé la machine la dernière fois
> powercfg /waketimers    # les minuteurs de réveil actifs (nécessite l'élévation)
```
