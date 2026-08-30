package org.springframework.samples.petclinic.visits.web;

import java.util.Collection;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-114: a pet named twice is asked for once, and the order the
 * caller gave survives.
 *
 * Passability: Collapse the identifiers before the repository call, preserving first-
 * seen order. The fixture captures the collection actually passed, so collapsing the
 * answer instead of the question does not pass, and an unordered set fails the order
 * assertion.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
@WebMvcTest(VisitResource.class)
@ActiveProfiles("test")
class BatchVisitRepeatAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    private Visit aVisit(int id, int petId) {
        return Visit.VisitBuilder.aVisit().id(id).petId(petId).build();
    }

    @SuppressWarnings("unchecked")
    private Collection<Integer> theIdentifiersAskedFor() {
        ArgumentCaptor<Collection<Integer>> captor = ArgumentCaptor.forClass(Collection.class);
        verify(visitRepository, times(1)).findByPetIdIn(captor.capture());
        return captor.getValue();
    }

    @Test
    void shouldAskForARepeatedPetOnlyOnce() throws Exception {
        given(visitRepository.findByPetIdIn(anyCollection()))
            .willReturn(List.of(aVisit(1, 111), aVisit(2, 222)));

        mvc.perform(get("/pets/visits?petId=111,222,111,222,111"))
            .andExpect(status().isOk());

        assertThat(List.copyOf(theIdentifiersAskedFor())).containsExactly(111, 222);
    }

    @Test
    void shouldKeepTheOrderTheCallerGave() throws Exception {
        given(visitRepository.findByPetIdIn(anyCollection()))
            .willReturn(List.of(aVisit(1, 222)));

        mvc.perform(get("/pets/visits?petId=222,111,333,111"))
            .andExpect(status().isOk());

        assertThat(List.copyOf(theIdentifiersAskedFor())).containsExactly(222, 111, 333);
    }

    @Test
    void shouldAnswerWithEachVisitOnce() throws Exception {
        given(visitRepository.findByPetIdIn(anyCollection()))
            .willReturn(List.of(aVisit(1, 111), aVisit(2, 222)));

        mvc.perform(get("/pets/visits?petId=111,111,222"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items.length()").value(2))
            .andExpect(jsonPath("$.items[0].id").value(1))
            .andExpect(jsonPath("$.items[1].id").value(2));
    }

    @Test
    void shouldLeaveADistinctRequestExactlyAsItWas() throws Exception {
        given(visitRepository.findByPetIdIn(anyCollection()))
            .willReturn(List.of(aVisit(1, 111), aVisit(2, 222), aVisit(3, 222)));

        mvc.perform(get("/pets/visits?petId=111,222"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items.length()").value(3))
            .andExpect(jsonPath("$.items[0].petId").value(111))
            .andExpect(jsonPath("$.items[2].petId").value(222));

        assertThat(List.copyOf(theIdentifiersAskedFor())).containsExactly(111, 222);
    }
}
