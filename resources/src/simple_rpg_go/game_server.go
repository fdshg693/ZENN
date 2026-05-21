// Go equivalent of game_server.ex.
//
// Elixir の game_loop(players) を goroutine + chan で再現する。
// receive 相当を select 文で書き、状態(players map)は for ループの
// ローカル変数として持ち回す。
package main

import (
	"fmt"
	"sort"
	"strings"
)

type MsgKind int

const (
	MsgJoin MsgKind = iota
	MsgPlay
	MsgQuit
)

type Message struct {
	Kind         MsgKind
	Name         string
	Hand         int
	PlayerMailbox chan<- Result
}

type Result struct {
	Text string
}

type playerState struct {
	mailbox chan<- Result
	hand    *int
}

var handNames = map[int]string{1: "Rock", 2: "Paper", 3: "Scissors"}

// Elixir の defp beats?/2 と同じ表 (1=Rock, 2=Paper, 3=Scissors)
func beats(h1, h2 int) bool {
	switch {
	case h1 == 1 && h2 == 2:
		return false
	case h1 == 1 && h2 == 3:
		return true
	case h1 == 2 && h2 == 3:
		return false
	}
	return false
}

func StartGameServer() chan<- Message {
	mailbox := make(chan Message, 16)
	go gameLoop(mailbox, map[string]playerState{})
	return mailbox
}

func gameLoop(mailbox <-chan Message, players map[string]playerState) {
	for {
		select {
		case msg := <-mailbox:
			switch msg.Kind {
			case MsgJoin:
				players[msg.Name] = playerState{mailbox: msg.PlayerMailbox}
			case MsgPlay:
				p := players[msg.Name]
				h := msg.Hand
				p.hand = &h
				players[msg.Name] = p
				if allHandsReady(players) {
					result := judgeGame(players)
					for _, info := range players {
						info.mailbox <- Result{Text: result}
					}
					players = map[string]playerState{}
				}
			case MsgQuit:
				return
			}
		}
	}
}

func allHandsReady(players map[string]playerState) bool {
	if len(players) == 0 {
		return false
	}
	for _, info := range players {
		if info.hand == nil {
			return false
		}
	}
	return true
}

func judgeGame(players map[string]playerState) string {
	names := make([]string, 0, len(players))
	for name := range players {
		names = append(names, name)
	}
	sort.Strings(names)

	parts := make([]string, 0, len(names))
	for _, name := range names {
		parts = append(parts, fmt.Sprintf("%s: %s", name, handNames[*players[name].hand]))
	}
	handsLine := strings.Join(parts, ", ")
	hands := map[string]int{}
	for _, name := range names {
		hands[name] = *players[name].hand
	}
	winners := findWinners(hands, names)
	return fmt.Sprintf("Result: %s → %s", handsLine, strings.Join(winners, ", "))
}

func findWinners(hands map[string]int, orderedNames []string) []string {
	seen := map[int]bool{}
	for _, h := range hands {
		seen[h] = true
	}
	unique := make([]int, 0, len(seen))
	for h := range seen {
		unique = append(unique, h)
	}
	sort.Ints(unique)

	switch len(unique) {
	case 1:
		return []string{"Draw!"}
	case 2:
		h1, h2 := unique[0], unique[1]
		winningHand := h2
		if beats(h1, h2) {
			winningHand = h1
		}
		winners := []string{}
		for _, name := range orderedNames {
			if hands[name] == winningHand {
				winners = append(winners, name)
			}
		}
		return []string{fmt.Sprintf("%s win!", strings.Join(winners, ", "))}
	default:
		return []string{"Three-way: Scissors beats Paper, Paper beats Rock, Rock beats Scissors - Draw!"}
	}
}
